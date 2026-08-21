from . import main_auto

app = main_auto.app


@app.get('/system_health')
def integrated_system_health():
    return main_auto.system_health()
