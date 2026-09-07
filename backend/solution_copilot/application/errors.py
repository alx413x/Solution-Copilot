class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def missing():
    return AppError(404, "NOT_FOUND", "资源不存在或无权访问。")


def forbidden():
    return AppError(403, "FORBIDDEN", "当前角色没有操作权限。")
