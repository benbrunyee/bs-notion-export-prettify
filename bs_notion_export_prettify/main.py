import logging
import shutil
import tempfile
import zipfile
from importlib.metadata import version
from os import listdir, path

from .args import parse_args, resolve_template_path
from .html_templator import HtmlTemplator
from .notion_html_manipulator import NotionHtmlManipulator
from .pdf_maker import PdfMaker
from .print_color import green, orange, red
from .resource_loader import ResourceLoader

logging.getLogger(__name__).addHandler(logging.NullHandler())


def prettify(
    input_file: str,
    output: str | None = None,
    template: str | None = None,
    title: str | None = None,
    subtitle: str | None = None,
    description: str | None = None,
    project: str | None = None,
    author: str | None = None,
    date: str | None = None,
    identifier: str | None = None,
    cover_page: bool = True,
    heading_numbers: bool = True,
    strip_internal_info: bool = True,
    table_of_contents: bool = True,
) -> str:
    """Convert a Notion HTML/ZIP export into a styled PDF.

    Returns the path to the generated PDF file.
    """
    resources = ResourceLoader()

    if template:
        resolved_template = resolve_template_path(template)
        template_dir = path.dirname(resolved_template)
        resources.set_folder(template_dir)

    with tempfile.TemporaryDirectory() as temp_dir:
        logging.debug("Temporary directory: %s", temp_dir)

        if input_file.endswith(".zip"):
            with zipfile.ZipFile(input_file, "r") as zip_ref:
                zip_ref.extractall(temp_dir)
        elif input_file.endswith(".html"):
            logging.debug("Copying HTML file to temporary directory")
            shutil.copy(input_file, temp_dir)
            input_asset_folder = input_file.replace(".html", "")
            if path.exists(input_asset_folder):
                shutil.copytree(
                    input_asset_folder,
                    path.join(temp_dir, path.basename(input_asset_folder)),
                )
        else:
            red("[ERROR] Unsupported input file format")
            raise ValueError(f"Unsupported input file format: {input_file}")

        html_files = [f for f in listdir(temp_dir) if f.endswith(".html")]
        if len(html_files) != 1:
            raise ValueError("Expected one HTML file in the zip file")
        html_file = path.join(temp_dir, html_files[0])

        # 0. Determine if there will be a cover page
        with_cover_page = cover_page and (
            resources.get_resource_path("cover.html")
            or resources.get_resource_path("cover.pdf")
        )

        # 1. - Manipulate the HTML
        manipulator = NotionHtmlManipulator(html_file)

        doc_metadata = {
            "title": title or manipulator.get_title(),
            "description": description or manipulator.get_description(),
            "subtitle": subtitle or "",
            "project": project or "",
            "author": author or "",
            "date": date or "",
            "identifier": identifier or "",
        }

        page_css = resources.get_resource_content("page.css")

        # 1.a. - Overwrite CSS
        if page_css:
            green("[PROC] Injecting page.css")
            manipulator.add_css_overwrites(page_css)
        else:
            orange("[SKIP] No page.css found")

        if css_overwrites := resources.get_resource_content("overwrites.css"):
            green("[PROC] Injecting overwrites.css")
            manipulator.add_css_overwrites(css_overwrites)
        else:
            orange("[SKIP] No overwrites.css found")

        # 1.b. - Remove internal info
        if strip_internal_info:
            green("[PROC] Removing internal info")
            manipulator.remove_internal_info()
            manipulator.remove_database_properties()
        else:
            orange("[SKIP] Keeping internal info (if any)")

        # 1.c. - Number headings
        if heading_numbers:
            green("[PROC] Numbering headings")
            manipulator.number_headings()
        else:
            orange("[SKIP] Headings kept as original")

        # 1.d. - Reset TOC
        if table_of_contents:
            green("[PROC] Processing TOC (if any in source)")
            manipulator.move_toc(keep=True)
        else:
            green("[PROC] Removing TOC (if any)")
            manipulator.move_toc(keep=False)

        # 1.e. - Handle Notion's header (title)
        if with_cover_page:
            green("[PROC] Removing header from source (in favour of cover page)")
            manipulator.remove_header()
        else:
            if header_template := resources.get_resource_content("header.html"):
                green("[PROC] Rendering and injecting new header block")
                title_block = HtmlTemplator(header_template).inject(doc_metadata).html
                manipulator.inject_title_block(title_block)
            else:
                orange("[SKIP] No HTML title template found. Keeping original header")

        # 1.x. - Save to file
        updated_html_path = path.join(temp_dir, "updated_doc.html")
        with open(updated_html_path, "w", encoding="utf-8") as f:
            f.write(manipulator.get_html())
            logging.debug("Updated HTML saved to %s", updated_html_path)

        # 2. - Convert to PDF
        pdf_maker = PdfMaker(temp_dir=temp_dir)
        green("[PROC] Generating main PDF document")
        pdf_maker.from_html_file(updated_html_path)

        # 2.a. - Add header/footer underlay
        # NOTE: this cannot be done as an overlay, due to a bug in PyMuPDF
        if underlay_template := resources.get_resource_content("background.html"):
            green("[PROC] Rendering underlay templates for each page")
            underlay_meta_template = HtmlTemplator(underlay_template).inject(
                doc_metadata,
                pageNumber="__PAGENUMBER__",
                hasCoverPage="hasCoverPage" if with_cover_page else "",
            )
            if page_css:
                underlay_meta_template.add_css(page_css)
            underlay_html = underlay_meta_template.html
            pdf_maker.merge_underlay_html(underlay_html)
        else:
            orange(
                "[SKIP] No HTML overlay template found. No headers and footers will be added"
            )

        # 2.b. - Merge branding background
        if background_file := resources.get_resource_path("background.pdf"):
            pdf_maker.merge_background_pdf(background_file)
            green("[PROC] Merging background PDF")
        else:
            orange("[SKIP] No PDF background file found")

        # 2.c. - Add cover page
        if with_cover_page:
            cover_html = "<html></html>"
            cover_template = resources.get_resource_content("cover.html")
            if cover_template:
                green("[PROC] Rendering cover template")
                cover_meta_template = HtmlTemplator(cover_template).inject(doc_metadata)
                if page_css:
                    cover_meta_template.add_css(page_css)
                cover_html = cover_meta_template.html
            else:
                orange("[SKIP] No HTML cover template found")

            cover_page_file = resources.get_resource_path("cover.pdf")
            if not cover_page_file:
                orange("[SKIP] No PDF cover page file found")

            green("[PROC] Prefixing with cover page")
            pdf_maker.prepend_cover_page(cover_page_file, cover_html)
        else:
            orange("[SKIP] Skipping cover page")

        # 3. - Add PDF TOC
        green("[PROC] Building PDF TOC")
        pdf_maker.make_toc(manipulator.get_heading_map())

        # 4. - Add metadata
        green("[PROC] Adding metadata")
        pdf_maker.set_metadata(
            dict(
                title=doc_metadata["title"],
                creator="Notion",
                producer=f"bs-notion-export-prettify v{version('bs-notion-export-prettify')}",
                author=doc_metadata["author"],
                subject=doc_metadata["description"],
            )
        )

        # 5. - Save to file
        output_file = output
        if not output_file:
            filename = doc_metadata["title"] + ".pdf"
            if doc_metadata["project"]:
                filename = doc_metadata["project"] + " - " + filename
            output_file = path.join(path.dirname(input_file), filename)

        pdf_maker.save(output_file)
        green("PDF generated at %s" % output_file)

        return output_file


def main():
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    args = parse_args()
    prettify(**vars(args))


if __name__ == "__main__":
    main()
