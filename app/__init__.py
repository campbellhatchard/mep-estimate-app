from .framework_compat import install_framework_compatibility


# Package import happens before app.main or any registration module is evaluated, making
# this the one safe boundary for compatibility with FastAPI/Starlette API transitions.
install_framework_compatibility()
