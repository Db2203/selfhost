import io

from PIL import Image

from app.queue import get_job_queue
from tests.test_assets import populated  # noqa: F401  (fixture)
from tests.test_auth import auth_header, login


class RecordingQueue:
    def __init__(self):
        self.jobs = []

    async def enqueue(self, job_name, *args, job_id=None):
        self.jobs.append(job_name)

    async def enqueue_and_wait(self, job_name, *args, timeout=30):
        self.jobs.append(job_name)
        return None


def jpeg_bytes(color="purple", size=(80, 60)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def upload(client, tokens, data, filename="phone.jpg"):
    return client.post(
        "/assets/upload",
        files={"file": (filename, data, "image/jpeg")},
        headers=auth_header(tokens),
    )


def test_upload_requires_auth(client):
    response = client.post(
        "/assets/upload", files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")}
    )
    assert response.status_code == 401


def test_upload_creates_asset_and_serves_original(populated, test_user):  # noqa: F811
    queue = RecordingQueue()
    populated.app.dependency_overrides[get_job_queue] = lambda: queue
    tokens = login(populated, test_user)

    response = upload(populated, tokens, jpeg_bytes())
    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False

    # The new asset appears in the timeline and its original is downloadable.
    page = populated.get("/assets", headers=auth_header(tokens)).json()
    assert page["total"] == 3  # 2 from the indexed library + 1 upload
    item = populated.get(f"/assets/{body['id']}", headers=auth_header(tokens)).json()
    original = populated.get(item["urls"]["original"])
    assert original.status_code == 200
    assert original.content == jpeg_bytes()

    # Post-processing jobs were enqueued.
    assert "thumbnail_backlog_job" in queue.jobs
    assert "embed_backlog_job" in queue.jobs
    assert "detect_faces_job" in queue.jobs


def test_duplicate_upload_is_a_noop(populated, test_user):  # noqa: F811
    populated.app.dependency_overrides[get_job_queue] = lambda: RecordingQueue()
    tokens = login(populated, test_user)

    first = upload(populated, tokens, jpeg_bytes("teal"))
    assert first.json()["duplicate"] is False
    second = upload(populated, tokens, jpeg_bytes("teal"), filename="copy.jpg")
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]

    page = populated.get("/assets", headers=auth_header(tokens)).json()
    assert page["total"] == 3  # not 4


def test_garbage_upload_is_rejected(populated, test_user):  # noqa: F811
    populated.app.dependency_overrides[get_job_queue] = lambda: RecordingQueue()
    tokens = login(populated, test_user)

    not_an_image = upload(populated, tokens, b"definitely not a jpeg")
    assert not_an_image.status_code == 400

    wrong_type = upload(populated, tokens, jpeg_bytes(), filename="evil.exe")
    assert wrong_type.status_code == 400
