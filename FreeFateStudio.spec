# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir）。

用法：
    pyinstaller FreeFateStudio.spec --noconfirm

产物：dist/FreeFateStudio/FreeFateStudio.exe
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for pkg in (
    "uvicorn",
    "langgraph",
    "langgraph.checkpoint.sqlite",
    "langchain_core",
    "langchain_deepseek",
    "lunar_python",
    "fastapi",
    "markdown",
    "sse_starlette",
):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# uvicorn 以字符串动态导入协议实现，必须显式声明
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "app",
    "app.api",
    "app.agent",
    "app.config",
    "app.server",
    "app.storage",
    "app.profile",
    "app.diagnostics",
    "app.tools",
    "app.tools.bazi",
    "app.tools.bazi_engine",
    "app.tools.liuyao",
    "app.tools.almanac",
    "app.tools.glossary",
    "app.tools.memory",
    "app.ui",
    "app.ui.theme",
    "app.ui.md",
    "app.ui.client",
    "app.ui.conv_list",
    "app.ui.icons",
    "app.ui.settings_popup",
    "app.ui.window",
]

excludes = [
    "tkinter",
    "matplotlib",
    "PIL",
    "pytest",
    "notebook",
    "IPython",
    "torch",
    "transformers",
    "tensorflow",
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("FreeFateStudio.ico", ".")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FreeFateStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="FreeFateStudio.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FreeFateStudio",
)
