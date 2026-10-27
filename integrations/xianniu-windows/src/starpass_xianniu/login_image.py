"""Decode official QR images, including JPEG (not supported by native Tk)."""
from io import BytesIO


def qr_photo(data, master):
    from PIL import Image, ImageTk
    if len(data) > 1048576:
        raise ValueError('官方二维码图片过大，请重新获取')
    with Image.open(BytesIO(data)) as source:
        if source.format not in ('PNG', 'JPEG') or not (1 <= source.width <= 2048 and 1 <= source.height <= 2048):
            raise ValueError('官方二维码图片格式异常，请重新获取')
        image = source.convert('RGB')
        image.thumbnail((310, 310), Image.Resampling.NEAREST)
        return ImageTk.PhotoImage(image, master=master)
