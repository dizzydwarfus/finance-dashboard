"""Resolve source dependencies through SECClient, then parse a fully local bundle."""
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urldefrag
import arelle
from lxml import etree
from .transport import safe_url
from .models import Problem
from .store import now

XML = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
REFERENCE_TAGS = {"schemaRef", "linkbaseRef", "import", "include", "redefine", "loc", "roleRef", "arcroleRef"}
MAX_BUNDLE = 200 * 1024 * 1024


def local_name(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def build_bundle(client, entry_url, directory, job_id=None):
    directory = Path(directory)
    files, sources, trees = {}, [], {}
    pending = [entry_url]
    total = 0
    while pending:
        original = urldefrag(pending.pop())[0]
        canonical = safe_url(original)
        if original in files:
            continue
        if len(files) >= 250:
            raise Problem(422, "too_many_dependencies", "A filing exceeds the dependency limit")
        parsed = urlsplit(canonical)
        bundled = None
        if parsed.hostname in {"www.xbrl.org", "www.w3.org"}:
            for scheme in ("https", "http"):
                candidate = Path(arelle.__file__).parent / "resources" / "cache" / scheme / parsed.hostname / parsed.path.lstrip("/")
                if candidate.is_file():
                    bundled = candidate.read_bytes()
                    break
        content = bundled if bundled is not None else client.get(canonical, job_id=job_id).content
        total += len(content)
        if total > MAX_BUNDLE:
            raise Problem(422, "filing_too_large", "A filing exceeds the 200 MiB dependency budget")
        suffix = Path(parsed.path).suffix.lower() or ".xml"
        path = directory / (sha256(original.encode()).hexdigest() + suffix)
        files[original] = path
        files.setdefault(canonical, path)
        sources.append({"url": original, "checksum": sha256(content).hexdigest(), "bytes": len(content), "retrievedAt": now().isoformat(), "availability": "available", "file": str(path)})
        try:
            tree = etree.fromstring(content, parser=XML)
        except etree.XMLSyntaxError:
            raise Problem(422, "invalid_xbrl_document", "A filing dependency is not well-formed XML/XHTML") from None
        if tree.getroottree().docinfo.doctype:
            # External entities are disabled; normal XHTML doctypes do not require retrieval.
            pass
        trees[original] = tree
        for element in tree.iter():
            if local_name(element.tag) not in REFERENCE_TAGS:
                continue
            reference = element.get("schemaLocation") or element.get("{http://www.w3.org/1999/xlink}href")
            if reference:
                target = urldefrag(urljoin(original, reference))[0]
                if target and target != original:
                    safe_url(target)
                    pending.append(target)
    for original, tree in trees.items():
        for element in tree.iter():
            for attribute in ("schemaLocation", "{http://www.w3.org/1999/xlink}href"):
                reference = element.get(attribute)
                if not reference or local_name(element.tag) not in REFERENCE_TAGS:
                    continue
                target, fragment = urldefrag(urljoin(original, reference))
                if target in files:
                    element.set(attribute, str(files[target]) + ("#" + fragment if fragment else ""))
        files[original].write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    return {"entrypoint": str(files[entry_url]), "sources": sources}
