import pydantic


class DerivedPreview(pydantic.BaseModel):
    """A rendered overview of a data asset, ready to become a derived asset."""

    image: bytes  # WEBP, RGBA, at most 1024 px on its longest side
    bounds_4326: tuple[float, float, float, float]  # lon/lat extent of the image
