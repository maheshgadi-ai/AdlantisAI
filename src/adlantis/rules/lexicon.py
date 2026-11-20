"""Wording that signals a health, environmental, or superlative claim.

Each pattern sits on its own line, and each has a test proving it fires.
"""

from __future__ import annotations

from adlantis.rules.text import bounded

_HEALTH_VERB = (
    r"(?:cur(?:e|es|ed|ing)|treat(?:s|ed|ing)?|heal(?:s|ed|ing)?|prevent(?:s|ed|ing)?"
    r"|reliev(?:e|es|ed|ing)|reduc(?:e|es|ed|ing)|lower(?:s|ed|ing)?|eas(?:e|es|ed|ing)"
    r"|sooth(?:e|es|ed|ing)|fight(?:s|ing)?|calm(?:s|ed|ing)?|beat(?:s|ing)?)"
)
_HEALTH_CONDITION = (
    r"(?:anxiety|depression|insomnia|stress(?!\s+on\b)|pain(?!\s+points?\b)|inflammation"
    r"|blood\s+pressure|blood\s+sugar|cholesterol|diabetes|cancer|arthritis"
    r"|fatigue|obesity|migraines?|headaches?|illness(?:es)?|diseases?|infections?)"
)
_SAME_CLAUSE = r"(?:[\s,'-]+[\w']+){0,4}?[\s,'-]+"

HEALTH = bounded(
    (
        _HEALTH_VERB + _SAME_CLAUSE + _HEALTH_CONDITION,
        r"(?:stress|anxiety|pain|headache)[\s-](?:relief|relieving|reducing|reliever)",
        r"(?:clinically|medically)[\s-](?:proven|tested|shown|approved)",
        r"doctors?[\s-](?:recommended|approved)",
        r"fda[\s-]approved",
        r"therapeutic",
        r"medicinal",
        r"detox(?:es|ify|ifies|ifying)?",
        r"anti[\s-]?inflammatory",
        r"anti[\s-]?aging",
        r"immune[\s-](?:boosting|support(?:ing)?)",
        r"boost(?:s|ing)?\s+(?:your\s+)?(?:immunity|immune\s+system|metabolism|energy|mood|memory|focus)",
        r"(?:sharpen(?:s|ing)?|improv(?:e|es|ing))\s+(?:your\s+)?"
        r"(?:focus|memory|sleep|mood|circulation|health)",
        r"heart[\s-]healthy",
        r"good\s+for\s+your\s+(?:heart|health|brain|body)",
        r"los(?:e|ing)\s+weight",
        r"weight[\s-]loss",
        r"burn(?:s|ing)?\s+(?:more\s+)?(?:fat|calories)",
        r"healthier\s+(?:you|life|lifestyle|heart|body|choice)",
        r"live\s+longer",
    )
)

ENVIRONMENTAL = bounded(
    (
        r"eco[\s-]?friendly",
        r"go(?:es|ing)?\s+green",
        r"green(?:er)?\s+(?:choice|alternative|option|commute|product|future|way|ride)",
        r"sustainabl[ey]",
        r"sustainability",
        r"carbon[\s-](?:neutral|negative|free|zero|positive)",
        r"net[\s-]zero",
        r"zero[\s-]emissions?",
        r"emissions?[\s-]free",
        r"(?:lower|reduced?|reduces|reducing|cuts?|cutting|fewer|less|no)\s+(?:\w+\s+){0,2}?emissions",
        r"(?:carbon|climate)\s+footprint",
        r"climate[\s-](?:friendly|positive|neutral|smart)",
        r"(?:planet|earth)[\s-]friendly",
        r"(?:saves?|saving|protects?|protecting|good\s+for|kind(?:er)?\s+to|better\s+for)"
        r"\s+(?:the\s+)?(?:planet|earth|environment)",
        r"environmentally\s+(?:friendly|safe|responsible|conscious)",
        r"biodegradable",
        r"compostable",
        r"recyclable",
        r"recycled",
        r"plastic[\s-]free",
        r"(?:ethically|responsibly)[\s-]sourced",
        r"fair[\s-]trade",
        r"organic(?!\s+(?:growth|traffic|reach|search|results?|chemistry))",
        r"all[\s-]natural",
        r"clean\s+energy",
        r"renewable\s+(?:energy|electricity|power)",
        r"carbon\s+offsets?",
        r"non[\s-]toxic",
    )
)

SUPERLATIVE = bounded(
    (
        r"(?<!step )(?<!issue )(?<!batch )(?<!lot )(?<!tip )(?<!part )#1",
        r"(?<!blend )(?<!batch )(?<!lot )(?<!roast )no\.\s?1",
        r"number[\s-]one(?![\s-](?:hundred|thousand))",
        r"(?<!all the )(?<!your )(?<!at )best"
        r"(?![\s-](?:before|regards|wishes|served|enjoyed|brewed|when|with|by|if|within|practices?)\b)",
        r"world'?s\s+first",
        r"first[\s-]ever",
        r"first\s+of\s+its\s+kind",
        r"finest",
        r"greatest",
        r"fastest",
        r"strongest",
        r"lightest(?!\s+roast)",
        r"cheapest",
        r"smoothest",
        r"freshest",
        r"purest",
        r"safest",
        r"quietest",
        r"most\s+(?:popular|trusted|advanced|powerful|reliable|awarded|loved|comfortable"
        r"|efficient|innovative|delicious|flavorful)",
        r"(?:industry|market|category|world)[\s-]leading",
        r"the\s+leading\s+(?:brand|maker|roaster|manufacturer|provider)",
        r"(?:market|industry)\s+leader",
        r"top[\s-](?:rated|ranked)",
        r"unbeatable",
        r"unmatched",
        r"unrivall?ed",
        r"unparalleled",
        r"second\s+to\s+none",
        r"award[\s-]winning",
        r"(?:scientifically|clinically|lab)[\s-]proven",
        r"proven\s+to",
        r"guaranteed\s+to",
        r"the\s+only\s+(?!thing\b)\w+\s+(?:that|with|to)",
    )
)
