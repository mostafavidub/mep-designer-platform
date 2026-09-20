from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import ArtifactBlob, Base, Project, Revision, User


def test_artifact_blob_is_available_from_a_separate_service_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shared.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    first = Session()
    user = User(email='artifact@example.test')
    first.add(user); first.flush()
    project = Project(user_id=user.id, name='shared artifact')
    first.add(project); first.flush()
    revision = Revision(project_id=project.id, revision_no=1, status='ready')
    first.add(revision); first.flush()
    blob = ArtifactBlob(
        project_id=project.id, revision_no=1, discipline='mechanical',
        filename='issued.dxf', media_type='application/dxf',
        sha256='a' * 64, content=b'validated-dxf-bytes',
    )
    first.add(blob); first.flush()
    revision.pdf_path = f'db://artifact/{blob.id}'
    first.commit(); blob_id = blob.id; project_id = project.id; first.close()

    second = Session()
    restored = second.get(ArtifactBlob, blob_id)
    assert restored.project_id == project_id
    assert restored.revision_no == 1
    assert bytes(restored.content) == b'validated-dxf-bytes'
    second.close()
