import io
import base64
import qrcode
from qrcode.image.pil import PilImage
from django.http import HttpResponse


def make_qr_image(payload: str, box_size: int = 8, border: int = 4) -> PilImage:
    """Creates a high-contrast, clean PIL QR image with quiet zone."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#000000", back_color="#ffffff")
    return img


def generate_access_qr_base64(token_or_code: str) -> str:
    """Returns Base64 Data URI string of parking access QR."""
    payload = f"sompark:pass:{token_or_code}"
    img = make_qr_image(payload, box_size=8, border=4)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f"data:image/png;base64,{encoded}"


def render_access_qr_response(token_or_code: str) -> HttpResponse:
    """Returns streaming PNG HttpResponse for direct image tags."""
    payload = f"sompark:pass:{token_or_code}"
    img = make_qr_image(payload, box_size=8, border=4)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    response = HttpResponse(buf.getvalue(), content_type='image/png')
    response['Cache-Control'] = 'public, max-age=3600'
    return response
