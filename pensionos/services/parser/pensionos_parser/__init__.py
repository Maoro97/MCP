"""PensionOS — מנוע קליטה ופענוח של קבצי המסלקה הפנסיונית."""

from .archive import ArchiveLimitError, iter_zip_members
from .issues import Code, Issue, Severity
from .mappings import MappingRegistry, UnknownStandardVersionError
from .models import PARSER_VERSION, ParseResult, ParseStatus, Product, Subject
from .pipeline import parse_bytes, parse_file
from .reconcile import national_id_hmac

__version__ = PARSER_VERSION

__all__ = [
    "ArchiveLimitError",
    "Code",
    "Issue",
    "MappingRegistry",
    "PARSER_VERSION",
    "ParseResult",
    "ParseStatus",
    "Product",
    "Severity",
    "Subject",
    "UnknownStandardVersionError",
    "iter_zip_members",
    "national_id_hmac",
    "parse_bytes",
    "parse_file",
]
