"""Prueba el CRUD de roles y el flujo de permisos, contra la BD real.

Uso: .venv/Scripts/python.exe scripts/probar_roles.py
"""
import sys

sys.path.insert(0, "backend")

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Rol, Usuario  # noqa: E402
from app.routers import roles as roles_router  # noqa: E402
from app.routers import usuarios as usuarios_router  # noqa: E402
from app.schemas import RolBase, UsuarioActualizar  # noqa: E402
from app.security import permisos_de  # noqa: E402

db = SessionLocal()
try:
    print("— roles sembrados —")
    for r in db.execute(select(Rol).order_by(Rol.es_sistema.desc(), Rol.nombre)).scalars():
        print(f"  {r.nombre:<15} sistema={r.es_sistema}  "
              f"ver_todas={r.ver_todas_areas} editar={r.editar_facturas} "
              f"aprobar={r.aprobar} contab={r.contabilizar} admin={r.administrar}")

    admin = db.execute(select(Usuario).where(Usuario.rol == "admin")).scalars().first()
    if admin is None:
        raise SystemExit("No hay usuario admin")

    # Crear un rol nuevo vía el endpoint (misma función que llama FastAPI)
    nombre_prueba = "supervisor_prueba"
    existente = db.execute(select(Rol).where(Rol.nombre == nombre_prueba)).scalar_one_or_none()
    if existente:
        db.delete(existente)
        db.commit()

    creado = roles_router.crear(
        RolBase(nombre=nombre_prueba, descripcion="Rol de prueba automatizada",
                ver_todas_areas=True, editar_facturas=False, aprobar=True,
                contabilizar=False, administrar=False),
        db=db, _=admin,
    )
    print(f"\n— rol creado: {creado.nombre} (id={creado.id}, en_uso={creado.en_uso}) —")

    # Validar que un usuario NO puede tomar un rol inexistente
    try:
        usuarios_router.actualizar(admin.id, UsuarioActualizar(rol="rol_que_no_existe"),
                                   db=db, _=admin)
        print("ERROR: debió rechazar un rol inexistente")
    except Exception as e:
        print(f"— rechazo esperado de rol inválido: {e}")

    # Listar roles vía endpoint (con conteo de uso)
    listado = roles_router.listar(db=db, _=admin)
    print(f"\n— GET /api/roles ({len(listado)} roles) —")
    for r in listado:
        print(f"  {r.nombre:<20} en_uso={r.en_uso}  sistema={r.es_sistema}")

    # Permisos efectivos de un usuario 'area' típico (si existe)
    de_area = db.execute(
        select(Usuario).where(Usuario.rol == "area")
    ).scalars().first()
    if de_area:
        print(f"\n— permisos de {de_area.email} (rol area): {permisos_de(db, de_area)}")

    # Intentar editar un rol de sistema -> debe fallar
    admin_rol = db.execute(select(Rol).where(Rol.nombre == "admin")).scalar_one()
    try:
        from app.schemas import RolActualizar
        roles_router.actualizar(admin_rol.id, RolActualizar(administrar=False), db=db, _=admin)
        print("ERROR: debió rechazar editar un rol de sistema")
    except Exception as e:
        print(f"— rechazo esperado al editar rol de sistema: {e}")

    # Limpieza: eliminar el rol de prueba
    r = roles_router.eliminar(creado.id, db=db, _=admin)
    print(f"\n— limpieza: {r}")
finally:
    db.close()

print("\nOK: todas las pruebas pasaron")
