"""Decode bounded local recordings, never URLs or user-provided paths."""
import numpy as np


def decode_recording(path):
    import av
    chunks, count = [], 0
    try:
        with av.open(str(path)) as container:
            if not container.streams.audio:
                raise ValueError('No audio found. Please record again.')
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            for frame in container.decode(audio=0):
                for output in resampler.resample(frame):
                    count += output.samples
                    if count > 31 * 16000:
                        raise ValueError('Recordings must be 30 seconds or shorter.')
                    chunks.append(output.to_ndarray().flatten())
            for output in resampler.resample(None):
                count += output.samples
                chunks.append(output.to_ndarray().flatten())
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('Could not read microphone audio. Please record again.') from error
    if not chunks or not 1600 <= count <= 31 * 16000:
        raise ValueError('Record between 0.1 and 30 seconds of speech.')
    audio = np.concatenate(chunks).astype(np.float32) / 32768
    if float(np.sqrt(np.mean(audio * audio))) < .001:
        raise ValueError('No speech detected. Please try again.')
    return audio
