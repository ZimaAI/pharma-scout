class PharmaError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        self.code, self.message, self.status, self.details = code, message, status, details or {}
        super().__init__(message)


def require(condition, code="NOT_FOUND", message="对象不存在或无权访问", status=404):
    if not condition:
        raise PharmaError(code, message, status)
