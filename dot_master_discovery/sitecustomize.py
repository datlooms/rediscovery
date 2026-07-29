try:
    import dot_frame_binding
except Exception:
    dot_frame_binding = None
if dot_frame_binding is not None and dot_frame_binding.is_configured():
    dot_frame_binding.install_if_configured()
