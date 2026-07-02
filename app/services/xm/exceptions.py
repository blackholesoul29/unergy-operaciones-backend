class FTPConnectionError(Exception):
    http_status = 503


class FTPAuthenticationError(Exception):
    http_status = 401


class FTPPermissionError(Exception):
    http_status = 403


class FTPFileNotFoundError(Exception):
    http_status = 404


class FTPTimeoutError(Exception):
    http_status = 504
