from pydantic import BaseModel, Field


class BaseRequest(BaseModel):
    request_id: str = Field(..., description="请求唯一 ID")
    group_id: str = Field(..., description="请求分组 ID")
    callback_type: str = Field(..., description="回调类型标识")
    timestamp: float = Field(..., description="请求时间戳（Unix seconds）")
