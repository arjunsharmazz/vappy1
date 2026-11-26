export default function DigitalFrame({ children, dragging, processing, onDragOver, onDragLeave, onDrop, frameRef }) {
  return <section ref={frameRef} className={`frame ${dragging ? 'dragging' : ''}`} aria-label="Portrait upload and preview" aria-busy={processing} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
    <div className="frame-inner">
      {children}
      <span className="frame-corner tl"/><span className="frame-corner tr"/><span className="frame-corner bl"/><span className="frame-corner br"/>
      {processing && <div className="processing-overlay"><span className="spinner"/>Analyzing portrait</div>}
    </div>
  </section>;
}
