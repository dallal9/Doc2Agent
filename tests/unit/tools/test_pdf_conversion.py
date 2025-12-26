from src.schemas import DocumentMetadata, DocumentSchema, PageSchema
from src.tools.pdf import document_schema_to_structured


def test_document_schema_to_structured_builds_spans_and_sections():
    doc = DocumentSchema(
        metadata=DocumentMetadata(
            doc_id="doc1",
            file_path="/tmp/doc.pdf",
            file_name="doc.pdf",
            file_size_bytes=10,
            page_count=1,
            subject="NDA",
        ),
        pages=[
            PageSchema(
                page_num=1,
                char_count=20,
                word_count=4,
                has_tables=False,
                has_images=False,
                text="INTRO:\n\nThis is a test paragraph.",
            )
        ],
    )

    structured = document_schema_to_structured(doc)

    assert structured.doc_type == "NDA"
    assert structured.sections == ["INTRO"]
    assert structured.citable_spans
    assert structured.citable_spans[0].page == 1

