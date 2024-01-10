# Built-in libraries
from dataclasses import dataclass
import datetime as dt
import re

# Third party libraries
from bs4.element import Tag


@dataclass
class Context:
    context_tag: Tag

    @property
    def contextId(self) -> str:
        """Get contextId

        Returns:
            str: contextId
        """
        return self.context_tag.attrs.get('id')

    @property
    def entity(self) -> str | None:
        """Get entity

        Returns:
            str: entity
        """
        return self.context_tag.find("entity").text.split()[
            0] if self.context_tag.find("entity") is not None else None

    @property
    def startDate(self) -> dt.datetime | None:
        """Get start date

        Returns:
            dt.datetime: start date
        """
        start = self.context_tag.find("startdate").text if self.context_tag.find(
            "startdate") is not None else None
        return dt.datetime.strptime(start, '%Y-%m-%d') if start is not None else None

    @property
    def endDate(self) -> dt.datetime | None:
        """Get end date

        Returns:
            dt.datetime: end date
        """
        end = self.context_tag.find("enddate").text if self.context_tag.find(
            "enddate") is not None else None
        return dt.datetime.strptime(end, '%Y-%m-%d') if end is not None else None

    @property
    def instant(self):
        """Get instant date

        Returns:
            dt.datetime: instant date
        """
        instant = self.context_tag.find("instant").text if self.context_tag.find(
            "instant") is not None else None
        return dt.datetime.strptime(instant, '%Y-%m-%d') if instant is not None else None

    @property
    def segment(self) -> dict | None:
        """Get segments and tags classifying the segment and store in dict

        Returns:
            dict: dict containing segment and tags classifying the segment
        """
        segment = self.context_tag.find("segment")

        if segment is None:
            return None

        segment_dict = {}

        segment_breakdown = segment.find_all(re.compile('^xbrldi:.*'))

        for i in segment_breakdown:
            segment_dict[i.attrs.get('dimension')] = i.text

        return segment_dict

    def to_dict(self) -> dict:
        """Convert context to dict

        Returns:
            dict: dict containing context information
        """
        return dict(contextId=self.contextId, entity=self.entity, segment=self.segment, startDate=self.startDate, endDate=self.endDate, instant=self.instant)

    def get_segment_length(self) -> int:
        """Get length of segment

        Returns:
            int: length of segment
        """
        segment = self.context_tag.find("segment")

        if segment is None:
            return 0

        return len(segment)

    def __repr__(self):
        return f'Context(contextId={self.contextId}, entity={self.entity}, segment={self.segment}, startDate={self.startDate}, endDate={self.endDate}, instant={self.instant})'

    def __repr_html__(self):
        return f"""
        <div style="border: 1px solid #ccc; padding: 10px; margin: 10px;">
            <h3>Context</h3>
            <p><strong>contextId:</strong> {self.contextId}</p>
            <p><strong>entity:</strong> {self.entity}</p>
            <p><strong>segment:</strong> {self.segment}</p>
            <p><strong>startDate:</strong> {self.startDate}</p>
            <p><strong>endDate:</strong> {self.endDate}</p>
            <p><strong>instant:</strong> {self.instant}</p>
        </div>
        """

    def __str__(self):
        return f'''contextId={self.contextId}
entity={self.entity}
segment={self.segment}
startDate={self.startDate}
endDate={self.endDate}
instant={self.instant}'''


@dataclass
class LinkLabels:
    label_tag: Tag

    @property
    def linkLabelId(self) -> str | None:
        """Get labelId

        Returns:
            str: labelId
        """
        return self.label_tag.attrs.get('id')

    @property
    def xlinkLabel(self) -> str | None:
        """Get linkLabel

        Returns:
            str: linkLabel
        """
        return self.label_tag.attrs.get('xlink:label')

    @property
    def xlinkRole(self) -> str | None:
        """Get linkRole

        Returns:
            str: linkRole
        """
        return self.label_tag.attrs.get('xlink:role')

    @property
    def xlinkType(self) -> str | None:
        """Get linkType

        Returns:
            str: linkType
        """
        return self.label_tag.attrs.get('xlink:type')

    @property
    def xlmnsXml(self) -> str | None:
        """Get xlmnsXml

        Returns:
            str: xlmnsXml
        """
        return self.label_tag.attrs.get('xmlns:xml')

    @property
    def xlmLang(self) -> str | None:
        """Get xlmLang

        Returns:
            str: xlmLang
        """
        return self.label_tag.attrs.get('xml:lang')

    @property
    def labelName(self) -> str | None:
        """Get labelName

        Returns:
            str: labelName
        """
        return self.label_tag.text if self.label_tag.text is not None else None

    def to_dict(self) -> dict:
        """Convert linkLabels to dict

        Returns:
            dict: dict containing linkLabels information
        """
        return dict(linkRole=self.linkRole, linkLabel=self.linkLabel, linkbase=self.linkbase)

    def __repr__(self):
        return f'LinkLabels(linkRole={self.linkRole}, linkLabel={self.linkLabel}, linkbase={self.linkbase})'

    def __repr_html__(self):
        return f"""
        <div style="border: 1px solid #ccc; padding: 10px; margin: 10px;">
            <h3>LinkLabels</h3>
            <p><strong>linkRole:</strong> {self.linkRole}</p>
            <p><strong>linkLabel:</strong> {self.linkLabel}</p>
            <p><strong>linkbase:</strong> {self.linkbase}</p>
        </div>
        """

    def __str__(self):
        return f'''linkRole={self.linkRole}
linkLabel={self.linkLabel}
linkBase={self.linkbase}'''


@dataclass
class Facts:
    fact_tag: Tag

    @property
    def factName(self):
        """Get factName

        Returns:
            str: factName
        """
        return self.fact_tag.name

    @property
    def factId(self):
        """Get factId

        Returns:
            str: factId
        """
        return self.fact_tag.attrs.get('id')

    @property
    def contextRef(self):
        """Get contextRef

        Returns:
            str: contextRef
        """
        return self.fact_tag.attrs.get('contextref')

    @property
    def unitRef(self):
        """Get unitRef

        Returns:
            str: unitRef
        """
        return self.fact_tag.attrs.get('unitref')

    @property
    def decimals(self):
        """Get decimals

        Returns:
            str: decimals
        """
        return self.fact_tag.attrs.get('decimals')

    @property
    def factValue(self):
        """Get factValue

        Returns:
            str: factValue
        """
        return self.fact_tag.text

    def to_dict(self) -> dict:
        """Convert facts to dict

        Returns:
            dict: dict containing facts information
        """
        return dict(factName=self.factName, factId=self.factId, contextRef=self.contextRef, unitRef=self.unitRef, decimals=self.decimals, factValue=self.factValue)

    def __repr__(self):
        return f'Facts(factName={self.factName}, factId={self.factId}, contextRef={self.contextRef}, unitRef={self.unitRef}, decimals={self.decimals}, factValue={self.factValue})'

    def __repr_html__(self):
        return f"""
        <div style="border: 1px solid #ccc; padding: 10px; margin: 10px;">
            <h3>Facts</h3>
            <p><strong>factName:</strong> {self.factName}</p>
            <p><strong>factId:</strong> {self.factId}</p>
            <p><strong>contextRef:</strong> {self.contextRef}</p>
            <p><strong>unitRef:</strong> {self.unitRef}</p>
            <p><strong>decimals:</strong> {self.decimals}</p>
            <p><strong>factValue:</strong> {self.factValue}</p>
        </div>
        """

    def __str__(self):
        return f'''factName={self.factName}
factId={self.factId}
contextRef={self.contextRef}
unitRef={self.unitRef}
decimals={self.decimals}
factValue={self.factValue}'''