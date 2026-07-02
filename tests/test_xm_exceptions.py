from app.services.xm.exceptions import (
    FTPConnectionError, FTPAuthenticationError, FTPPermissionError,
    FTPFileNotFoundError, FTPTimeoutError,
)


def test_http_status_codes():
    assert FTPConnectionError("x").http_status == 503
    assert FTPAuthenticationError("x").http_status == 401
    assert FTPPermissionError("x").http_status == 403
    assert FTPFileNotFoundError("x").http_status == 404
    assert FTPTimeoutError("x").http_status == 504
