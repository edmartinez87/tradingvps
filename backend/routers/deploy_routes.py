"""Self-hosting routes (/api/deploy/*): version info and the downloadable source package for the user's own VPS."""
import asyncio
import logging

from fastapi import HTTPException
from fastapi.responses import Response

import deploy_pkg
from deps import engine, protected_router

logger = logging.getLogger(__name__)
router = protected_router()


@router.get("/deploy/info")
async def deploy_info():
    return await asyncio.to_thread(deploy_pkg.info)


@router.get("/deploy/package")
async def deploy_package():
    try:
        data, name, v = await asyncio.to_thread(deploy_pkg.build)
    except FileNotFoundError:
        raise HTTPException(404, "Esta instalación no incluye el código fuente: descarga el paquete desde el panel de desarrollo (preview)")
    except Exception as e:
        logger.exception("deploy package")
        raise HTTPException(500, f"No se pudo generar el paquete: {str(e)[:160]}")
    await engine.log("INFO", f"Paquete de instalación descargado · {name} · {round(len(data) / 1048576, 2)} MB · versión {v['version']}")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Package-Version": v["version"]})
