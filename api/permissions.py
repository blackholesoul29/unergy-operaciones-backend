"""Permisos por rol.

Portado de `api/permissions.py` de Origina. El contrato es identico y por eso
son intercambiables: la vista declara `required_role` y el permiso lee
`request.user.roles` (una lista de strings). Que el token venga de un servicio
gRPC (Origina) o se valide en proceso (aca, ver `api/authentication.py`) no le
importa a este archivo.

El chequeo va en `has_permission`, NUNCA solo en `has_object_permission`: DRF no
llama el object-level en `list` ni en `create`, asi que un permiso solo
object-level deja el POST abierto.
"""

from rest_framework import permissions

ADMIN_ROLE = "admin"

# Roles que solo pueden leer. Se descartan de la lista del usuario ANTES de
# evaluar un metodo no seguro, para que aparecer en `required_role` de un
# listado no habilite POST/PATCH/DELETE del mismo recurso.
READ_ONLY_ROLES = frozenset({"solo_lectura"})


class RolePermission(permissions.BasePermission):
    """Exige que el usuario tenga alguno de los roles de `view.required_role`.

    `admin` pasa siempre. Sin `required_role` en la vista, basta estar
    autenticado — declararlo es responsabilidad de la vista, igual que en
    Origina.
    """

    message = "No tienes el rol necesario para esta operación."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        roles = set(getattr(user, "roles", None) or [])
        if not roles:
            return False
        if ADMIN_ROLE in roles:
            return True

        required = set(getattr(view, "required_role", None) or [])
        if not required:
            return True

        if request.method not in permissions.SAFE_METHODS:
            roles -= READ_ONLY_ROLES
        return bool(roles & required)
