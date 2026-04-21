"""Command-line interface for poolbridge."""

import argparse
import logging
import sys
from typing import List, Optional

from poolbridge.converter import PoolBridgeConverter
from poolbridge.validation import ValidationError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="poolbridge",
        description=(
            "Convert Emlid Reach survey CSV exports to Pool Studio DXF format.\n\n"
            "Example:\n"
            "  poolbridge convert survey.csv -c config.yaml -o pool_site.dxf"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="poolbridge 0.1.0")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging output.",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    _add_convert_command(sub)
    return parser


def _add_convert_command(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "convert",
        help="Convert an Emlid CSV to DXF.",
        description="Run the 6-stage conversion pipeline on an Emlid Flow CSV export.",
    )

    p.add_argument(
        "input",
        metavar="INPUT_CSV",
        help="Path to the Emlid Flow CSV export file.",
    )
    p.add_argument(
        "-c", "--config",
        metavar="CONFIG",
        default=None,
        help="Path to a poolbridge YAML or JSON config file. "
             "If omitted, built-in defaults are used.",
    )
    p.add_argument(
        "-o", "--output",
        metavar="OUTPUT_DXF",
        default=None,
        help="Path for the output DXF file. "
             "Defaults to INPUT_CSV with .dxf extension.",
    )
    p.add_argument(
        "--crs",
        metavar="EPSG_CODE",
        default=None,
        help="Target CRS for reprojection (e.g. 'EPSG:32614'). "
             "Overrides coordinate_system.target_crs in config.",
    )
    p.add_argument(
        "--z-offset",
        metavar="METERS",
        type=float,
        default=None,
        help="Z datum offset in meters added to all elevations before unit conversion. "
             "Overrides z_datum.offset in config.",
    )
    p.add_argument(
        "--no-localize",
        action="store_true",
        dest="skip_localization",
        help="Skip the localization step even if control points are defined in config.",
    )
    p.add_argument(
        "--no-penzd",
        action="store_true",
        dest="skip_penzd",
        help="Suppress the secondary PENZD CSV export.",
    )


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=level,
        stream=sys.stderr,
    )


def _derive_output_path(input_csv: str) -> str:
    import os
    base = os.path.splitext(input_csv)[0]
    return base + ".dxf"


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the poolbridge CLI.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "convert":
        return _run_convert(args)

    parser.print_help()
    return 1


def _run_convert(args: argparse.Namespace) -> int:
    output_dxf = args.output or _derive_output_path(args.input)

    # Temporarily patch config to disable PENZD if --no-penzd
    try:
        converter = PoolBridgeConverter(config_path=args.config)

        if args.skip_penzd:
            converter.config.setdefault("output", {})["export_penzd_csv"] = False

        result = converter.convert(
            input_csv=args.input,
            output_dxf=output_dxf,
            target_crs=args.crs,
            z_offset=args.z_offset,
            skip_localization=args.skip_localization,
        )

        print(str(result))
        return 0

    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (ValidationError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        logging.exception("Traceback:")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
