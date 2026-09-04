"""Decoradores de logging para vistas — `@class_logger_wrapper` y `@log_endpoint`.

Portados de `logger/logger.py` de Origina (696 lineas) reducidos a lo que este
repo necesita. Dos diferencias que no son simplificaciones sino decisiones:

**1. Aca se re-lanza la excepcion; en Origina se la traga.** El `log_endpoint`
de Origina captura la excepcion y devuelve una respuesta RFC 9457 en su lugar.
Eso cambia el contrato de error de CADA endpoint que decora, y este backend
tiene 493 endpoints cuyo formato de error (`{"detail": ...}`) ya consume el
frontend. Loguear no puede cambiar la respuesta: se registra y se re-lanza, y
el manejador de excepciones de DRF decide el cuerpo.

**2. Sin Discord, sin ELK, sin Filebeat.** Origina escribe JSON a
`logs/{dominio}.log` y Filebeat los envia. Aca se usa `logging` de la stdlib y
la configuracion de handlers vive en `config/settings.py`, donde ya la mira
quien opera el despliegue.

Lo que si se copia, porque migration.md no lo documenta y los serializers de
Origina dependen de ello: `class_logger_wrapper` tambien inyecta `uuid`
(el id de request) y `request` en el contexto del serializer.
"""

import functools
import logging
import time
import uuid as uuid_lib

_ACCIONES_CRUD = ("list", "retrieve", "create", "update", "partial_update", "destroy")


def get_logger(nombre: str) -> logging.Logger:
    return logging.getLogger(f"operaciones.{nombre}")


def log_endpoint(name: str):
    """Loguea una accion de vista: quien, cuanto tardo, y si fallo — y re-lanza.

    Va en cada `@action` custom: `class_logger_wrapper` solo cubre el CRUD
    estandar.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, request, *args, **kwargs):
            log = get_logger(name)
            inicio = time.monotonic()
            usuario = getattr(getattr(request, "user", None), "id", None)
            try:
                respuesta = func(self, request, *args, **kwargs)
            except Exception as exc:
                log.exception(
                    "%s falló: %s", name, exc,
                    extra={"usuario_id": usuario, "ruta": request.path},
                )
                raise                       # ver docstring del modulo, punto 1
            log.info(
                "%s ok en %.0f ms", name, (time.monotonic() - inicio) * 1000,
                extra={"usuario_id": usuario, "ruta": request.path},
            )
            return respuesta

        return wrapper

    return decorator


def class_logger_wrapper(name: str):
    """Decora las acciones CRUD del ViewSet e inyecta el id de request al contexto.

    Las `@action` custom NO quedan cubiertas: llevan su propio `@log_endpoint`.
    """

    def decorator(cls):
        for accion in _ACCIONES_CRUD:
            metodo = getattr(cls, accion, None)
            if metodo is not None:
                setattr(cls, accion, log_endpoint(f"{name} | {accion}")(metodo))

        contexto_original = cls.get_serializer_context

        @functools.wraps(contexto_original)
        def get_serializer_context(self):
            contexto = contexto_original(self)
            contexto["uuid"] = getattr(
                self.request, "request_id", None
            ) or str(uuid_lib.uuid4())
            return contexto

        cls.get_serializer_context = get_serializer_context
        return cls

    return decorator
