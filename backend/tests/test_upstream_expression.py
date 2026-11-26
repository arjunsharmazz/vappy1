"""Compare extracted expression math with the pinned upstream implementation."""
import ast
from pathlib import Path
import unittest
import numpy as np
from app.vendor.liveportrait import expression


class UpstreamExpressionTests(unittest.TestCase):
    def test_extracted_controls_match_upstream(self):
        path = Path(__file__).resolve().parents[2] / 'third_party/LivePortrait/src/gradio_pipeline.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        pipeline = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GradioPipeline')
        for node in pipeline.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith('update_delta_new_'):
                continue
            local = getattr(expression, getattr(node, 'name', ''), None)
            if local is None:
                continue
            node.decorator_list = []
            namespace = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
            for value in [-6., 0., 6.]:
                source = np.random.default_rng(9).normal(size=(1, 21, 3)).astype(np.float32)
                expected = source.copy()
                actual = source.copy()
                args = [value, value / 2] if 'eyeball' in node.name else [value]
                namespace[node.name](None, *args, expected)
                local(*args, actual)
                np.testing.assert_array_equal(actual, expected, err_msg=node.name)

    def test_lip_depth_does_not_move_mouth_sideways(self):
        delta = np.zeros((1, 21, 3), dtype=np.float32)
        expression.update_delta_new_lip_variation_two(6, delta)
        np.testing.assert_array_equal(delta[:, :, 0], 0)
        self.assertNotEqual(delta[0, 20, 2], 0)
