"""Offline Arelle subprocess. No HTTP is permitted in this process."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import socket
import sys
from arelle.api.Session import Session
from arelle.RuntimeOptions import RuntimeOptions
from arelle import XbrlConst
from lxml import etree
from .parse_diagnostics import ParseFailure, PARSE_MESSAGES, diagnostic_codes


def qname(value):
    return f"{{{value.namespaceURI}}}{value.localName}" if value is not None else ""


def date_text(value):
    return value.date().isoformat() if value is not None else None


def parse_bundle(bundle, cache_dir):
    def no_network(*args, **kwargs):
        raise RuntimeError("Parser network access is forbidden; download dependencies through SECClient")
    socket.create_connection = no_network
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    source_map = {str(Path(source["file"]).resolve()): source["url"] for source in bundle["sources"]}
    output = {"facts": [], "contexts": [], "units": [], "labels": [], "relationships": [], "warnings": []}
    options = RuntimeOptions(entrypointFile=bundle["entrypoint"], cacheDirectory=str(cache_dir),
                             internetConnectivity="offline", disablePersistentConfig=True, keepOpen=True, validate=True, formulaAction="none",
                             plugins=f"inlineXbrlDocumentSet|{Path(__file__).parent / 'vendor' / 'sec_transform'}", logFile="logToBuffer")
    with Session() as session:
        loaded = session.run(options)
        models = session.get_models()
        if not loaded or not models:
            raise ValueError("Arelle could not load the filing")
        for model in models:
            fatal_codes = ("IOerror", "FileNotLoadable", "schemaImportMissing", "schemaFileMissing", "xmlSchema:")
            if any(str(code).startswith(fatal_codes) for code in model.errors):
                raise ParseFailure("parse_dependency_missing", model.errors)
            for context in model.contexts.values():
                dimensions = []
                for axis, value in sorted(context.qnameDims.items(), key=lambda item: qname(item[0])):
                    dimensions.append({"axis": qname(axis), "member": qname(value.memberQname) if value.isExplicit else None,
                                       "typedValue": etree.tostring(value.typedMember, method="c14n").decode() if value.isTyped else None})
                # Arelle end/instant datetimes are exclusive; expose the original inclusive filing date.
                row = {"contextRef": context.id, "entityScheme": context.entityIdentifier[0], "entity": context.entityIdentifier[1],
                       "periodType": "instant" if context.isInstantPeriod else "duration" if context.isStartEndPeriod else "forever",
                       "startDate": date_text(context.startDatetime) if context.isStartEndPeriod else None,
                       "endDate": date_text(context.endDatetime - timedelta(days=1)) if context.isStartEndPeriod else None,
                       "instant": date_text(context.instantDatetime - timedelta(days=1)) if context.isInstantPeriod else None,
                       "dimensions": dimensions}
                output["contexts"].append(row)
            contexts = {row["contextRef"]: row for row in output["contexts"]}
            for unit in model.units.values():
                output["units"].append({"unitRef": unit.id, "numerator": [qname(v) for v in unit.measures[0]], "denominator": [qname(v) for v in unit.measures[1]]})
            for ordinal, fact in enumerate(sorted(model.factsInInstance, key=lambda f: (source_map.get(str(Path(f.modelDocument.filepath).resolve()), ""), f.objectIndex))):
                concept = fact.concept
                if concept is None:
                    raise ValueError("A fact references an unresolved taxonomy concept")
                if not concept.isNumeric:
                    continue
                context = contexts.get(fact.contextID)
                if not context:
                    raise ValueError("A numeric fact references a missing context")
                raw_value, numeric = fact.value, None
                if not fact.isNil:
                    try:
                        value = Decimal(str(fact.xValue))
                        if not value.is_finite():
                            raise ValueError("A fact has a non-finite numeric value")
                        numeric = format(value, "f")
                    except (InvalidOperation, TypeError):
                        raise ValueError("A numeric fact failed XBRL value conversion") from None
                source_path = str(Path(fact.modelDocument.filepath).resolve())
                source_url = source_map.get(source_path, "")
                output["facts"].append({"ordinal": ordinal, "concept": qname(fact.qname), "label": concept.label(lang="en-US", fallbackToQname=True),
                    "value": numeric, "rawValue": raw_value, "nil": bool(fact.isNil), "unitRef": fact.unitID, "decimals": fact.decimals,
                    "contextRef": fact.contextID, "dimensions": context["dimensions"], "startDate": context["startDate"], "endDate": context["endDate"], "instant": context["instant"],
                    "sourceUrl": source_url, "sourceId": fact.id, "sourcePath": fact.getroottree().getpath(fact)})
            label_set = model.relationshipSet(XbrlConst.conceptLabel)
            for concept in model.qnameConcepts.values():
                for relationship in label_set.fromModelObject(concept):
                    label = relationship.toModelObject
                    output["labels"].append({"concept": qname(concept.qname), "role": label.role, "language": label.xmlLang, "text": label.textValue})
            for arcrole in (XbrlConst.summationItem, XbrlConst.parentChild, XbrlConst.all, XbrlConst.notAll, XbrlConst.hypercubeDimension, XbrlConst.dimensionDomain, XbrlConst.domainMember, XbrlConst.dimensionDefault):
                for relationship in model.relationshipSet(arcrole).modelRelationships:
                    output["relationships"].append({"arcrole": arcrole, "role": relationship.linkrole, "fromConcept": qname(relationship.fromModelObject.qname), "toConcept": qname(relationship.toModelObject.qname), "order": str(relationship.order), "weight": str(relationship.weight) if arcrole == XbrlConst.summationItem else None})
            output["warnings"].extend(sorted({str(code) for code in model.errors})[:50])
    if not output["facts"]:
        raise ValueError("This filing contains no supported numeric XBRL facts")
    return output


if __name__ == "__main__":
    try:
        bundle = json.loads(Path(sys.argv[1]).read_text())
        result = parse_bundle(bundle, Path(sys.argv[1]).parent / "cache")
        Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        code = error.code if isinstance(error, ParseFailure) else "parse_failed"
        diagnostics = error.diagnostics if isinstance(error, ParseFailure) else diagnostic_codes(["python:" + type(error).__name__])
        # Publish only controlled messages and bounded codes, never raw Arelle logs or source text.
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(json.dumps({"error": {"code": code, "message": PARSE_MESSAGES[code], "diagnostics": diagnostics}}))
        print(PARSE_MESSAGES[code], file=sys.stderr)
        sys.exit(1)
