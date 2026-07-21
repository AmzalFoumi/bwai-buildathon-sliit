"""Laptop Store Helpdesk — tools for querying the laptop catalogue."""

from __future__ import annotations

import csv
import os
from typing import Literal

# ── Data Loading ──────────────────────────────────────────────────────────────
# Paths and constants used to locate and parse the laptop catalogue CSV.

_DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CSV_PATH = os.path.join(_DATA_DIR, "laptop_dataset_final.csv")

# -- Intent-matching keyword lists ---------------------------------------------
# These lists define the hardware patterns that help us classify laptops
# into usage categories (gaming, business, etc.).

# Dedicated GPU substrings → a laptop is likely capable of gaming / 3D work
_GAMING_KEYWORDS = [
    "nvidia geforce rtx", "nvidia geforce gtx", "nvidia quadro",
    "amd radeon rx", "amd radeon pro",
]

# Laptop series that are designed for business / enterprise use
_BUSINESS_KEYWORDS = [
    "thinkpad", "elitebook", "probook", "latitude", "precision",
]

# Weight (kg) below which a laptop is considered thin-and-light / ultraportable
_THIN_AND_LIGHT_THRESHOLD = 1.6  # kg


# ── Internal helpers ──────────────────────────────────────────────────────────
# These functions are private to this module.  They handle data loading,
# parsing raw CSV strings into numbers, and category classification.


def _load_data() -> list[dict]:
    """Load laptop records from the CSV file into a list of dicts.

    Each CSV row becomes one dict keyed by the column names.  Two synthetic
    fields are added:
      - ``_price``      → float  (normalised from "Price (Rs)")
      - ``_weight_kg``  → float  (extracted from the "Weight" column)

    Returns:
        Every row from the CSV, including rows with missing prices.
        Downstream tools filter those out when appropriate.
    """
    rows: list[dict] = []
    with open(_CSV_PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalise price: strip whitespace, convert to float (default 0.0)
            raw = row.get("Price (Rs)", "").strip()
            row["_price"] = float(raw) if raw else 0.0

            # Normalise weight: parse "1.41 Kg weight (Light-weight)" → 1.41
            w = row.get("Weight", "").strip().lower()
            row["_weight_kg"] = _parse_weight(w)

            rows.append(row)
    return rows


def _parse_weight(raw: str) -> float:
    """Extract numeric weight in kilograms from a string like ``'1.41 Kg weight'``.

    Args:
        raw: The raw Weight column value.

    Returns:
        Weight in kg, or 0.0 if no pattern matches.
    """
    # Look for a decimal number followed by whitespace and 'k' (case-insensitive).
    import re
    m = re.search(r"([\d.]+)\s*k", raw)
    return float(m.group(1)) if m else 0.0


def _parse_display_size(raw: str) -> float:
    """Extract numeric display size in inches from a string like ``'15.6 Inches (39.62 cm)'``.

    Args:
        raw: The raw Display Size column value.

    Returns:
        Diagonal size in inches, or 0.0 if no pattern matches.
    """
    import re
    m = re.search(r"([\d.]+)\s*Inch", raw)
    return float(m.group(1)) if m else 0.0


def _match_budget_category(price: float) -> str:
    """Classify a price point into a human-friendly budget tier.

    Args:
        price: Price in Rupees.

    Returns:
        One of ``'budget'``, ``'mid-range'``, ``'premium'``, ``'ultra-premium'``.
    """
    if price <= 35000:
        return "budget"
    elif price <= 65000:
        return "mid-range"
    elif price <= 100000:
        return "premium"
    else:
        return "ultra-premium"


# ── Intent classifier ─────────────────────────────────────────────────────────
# ``_matches_intent`` uses simple keyword / threshold heuristics to decide
# whether a laptop is suitable for a given use case.  This lets the agent
# answer questions like "Which laptop is good for gaming?" without the
# customer having to specify technical specs.


def _matches_intent(row: dict, intent: str) -> bool:
    """Return ``True`` if *row* looks suitable for the given usage *intent*.

    Heuristics are based on GPU, RAM, processor, weight, display size,
    and known product series.  When no intent is matched the function
    returns ``True`` (pass-through).

    Args:
        row: A single laptop record (augmented with ``_price``, ``_weight_kg``).
        intent: Lower-cased usage keyword (e.g. ``'gaming'``, ``'student'``).

    Returns:
        Whether the laptop passes the intent filter.
    """
    # Cache frequently accessed fields so we only call .get() / .lower() once.
    intent = intent.lower()
    gpu = row.get("Graphic Processor", "").lower()
    brand = row.get("Brand", "").lower()
    series = row.get("Series", "").lower()
    model = row.get("Model", "").lower()
    weight = row.get("_weight_kg", 0)
    ram = row.get("Capacity", "")
    processor = row.get("Processor", "").lower()
    display_size = _parse_display_size(row.get("Display Size", ""))

    # --- Gaming ---
    # Requires a dedicated GPU (NVIDIA RTX/GTX or AMD Radeon RX/Pro) AND
    # either ample RAM (≥16 GB) or a known gaming-series chassis.
    if intent in ("gaming", "game", "gamer"):
        has_dedicated_gpu = any(kw in gpu for kw in _GAMING_KEYWORDS)
        has_gaming_series = any(
            kw in series
            for kw in ("gaming", "predator", "tuf", "rog", "legion", "omen", "victus")
        )
        good_ram = ram in ("16 GB", "32 GB", "64 GB")
        return has_dedicated_gpu and (good_ram or has_gaming_series)

    # --- Student / General Use ---
    # Affordable (≤ Rs. 65 000) and reasonably portable (≤ 2.0 kg).
    if intent in ("student", "study", "college", "general"):
        good_price = row["_price"] <= 65000
        portable = weight <= 2.0
        return good_price and portable

    # --- Business / Office ---
    # Known business series (ThinkPad, EliteBook, etc.) OR a combination of
    # long battery life (column non-empty) and lightweight design.
    if intent in ("business", "office", "professional", "work"):
        has_business_series = any(
            kw in series or kw in model
            for kw in _BUSINESS_KEYWORDS
        )
        good_battery = row.get("Battery Life", "") != ""
        if has_business_series:
            return True
        return good_battery and weight <= 1.8

    # --- Creative / Content Creation ---
    # Needs a dedicated GPU, ≥16 GB RAM, and a ≥15" display for detailed work.
    if intent in ("creative", "content creation", "design", "video editing", "photo editing"):
        has_dedicated_gpu = any(kw in gpu for kw in _GAMING_KEYWORDS)
        good_ram = ram in ("16 GB", "32 GB", "64 GB")
        good_display = _parse_display_size(row.get("Display Size", "")) >= 15.0
        return has_dedicated_gpu and good_ram and good_display

    # --- Portable / Lightweight ---
    # Weight must be below the thin-and-light threshold (1.6 kg).
    if intent in ("portable", "lightweight", "thin", "ultrabook"):
        return weight <= _THIN_AND_LIGHT_THRESHOLD

    # --- Programming / Development ---
    # Needs ≥16 GB RAM and a modern mid/high-end processor.
    if intent in ("programming", "development", "coding", "developer"):
        good_ram = ram in ("16 GB", "32 GB", "64 GB")
        good_processor = any(
            kw in processor
            for kw in ("i5", "i7", "i9", "ryzen 5", "ryzen 7", "ryzen 9", "core ultra")
        )
        return good_ram and good_processor

    # No intent matched → pass everything through
    return True


# ── Tools ─────────────────────────────────────────────────────────────────────
# Each function below is registered as a tool on the ADK agent.  They all
# accept plain Python types and return serialisable dicts so the agent can
# interpret the results.


def search_laptops(
    brand: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_ram: str | None = None,
    min_storage: str | None = None,
    processor_keyword: str | None = None,
    intent: Literal[
        "gaming", "student", "business", "creative",
        "portable", "programming", "general",
    ] | None = None,
    sort_by: Literal["price", "ram", "storage"] | None = None,
    ascending: bool = True,
    limit: int = 20,
) -> dict:
    """Search the laptop catalogue with multiple optional filters.

    Each filter is AND-ed together.  When *intent* is provided the tool applies
    smart heuristics so that the results match the intended use case.

    Args:
        brand: Laptop brand name (e.g. "Asus", "HP", "Dell", "Lenovo"). Case-insensitive.
        min_price: Minimum price in Rupees.
        max_price: Maximum price in Rupees.
        min_ram: Minimum RAM (e.g. "8 GB", "16 GB").
        min_storage: Minimum SSD storage (e.g. "256 GB", "512 GB", "1 TB").
        processor_keyword: Filter processor name (e.g. "i5", "i7", "Ryzen 7").
        intent: Usage category for smart recommendations.
        sort_by: Field to sort results by.
        ascending: Sort ascending (True) or descending (False).
        limit: Maximum number of results to return.

    Returns:
        Matching laptops with count and summary stats.
    """
    data = _load_data()
    results: list[dict] = []

    # ── Filter pipeline ────────────────────────────────────────────────────
    # Each row is tested against every active filter.  Filters are AND-ed
    # together so only rows that satisfy ALL criteria are kept.

    for row in data:
        # Skip rows with no valid price unless user explicitly searches by some non-price field
        if row["_price"] <= 0 and min_price is None and max_price is None:
            continue

        # -- Brand filter --
        # Case-insensitive substring match on the Brand column.
        if brand and brand.lower() not in row.get("Brand", "").lower():
            continue

        # -- Price filters --
        # Both lower and upper bounds are optional; only those supplied are enforced.
        price = row["_price"]
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue

        # -- RAM filter --
        # Uses ``_capacity_gte`` to compare values like "8 GB" vs "16 GB" correctly.
        if min_ram:
            row_ram = row.get("Capacity", "").strip()
            if not _capacity_gte(row_ram, min_ram):
                continue

        # -- Storage filter --
        # Same comparison logic for SSD capacity.
        if min_storage:
            row_storage = row.get("SSD Capacity", "").strip()
            if not _capacity_gte(row_storage, min_storage):
                continue

        # -- Processor keyword --
        # Simple substring match on the Processor column (e.g. "i7", "Ryzen 5").
        if processor_keyword:
            if processor_keyword.lower() not in row.get("Processor", "").lower():
                continue

        # -- Intent filter --
        # Uses the heuristic classifier defined above.
        if intent and not _matches_intent(row, intent):
            continue

        results.append(row)

    # ── Sorting ────────────────────────────────────────────────────────────
    # Sort the filtered results by the requested field and direction.
    if sort_by == "price":
        results.sort(key=lambda r: r["_price"], reverse=not ascending)
    elif sort_by == "ram":
        results.sort(
            key=lambda r: _parse_capacity_gb(r.get("Capacity", "")),
            reverse=not ascending,
        )
    elif sort_by == "storage":
        results.sort(
            key=lambda r: _parse_capacity_gb(r.get("SSD Capacity", "")),
            reverse=not ascending,
        )

    # ── Limit & summarise ──────────────────────────────────────────────────
    results = results[:limit]

    # Compute a simple average price for the result set (useful for "how much
    # will a decent gaming laptop cost?" questions).
    if results:
        prices = [r["_price"] for r in results]
        avg_price = sum(prices) / len(prices)
    else:
        avg_price = 0

    return {
        "status": "success",
        "count": len(results),
        "total_matching": len(results),  # same as count after limit
        "avg_price_rs": round(avg_price, 2),
        "laptops": [
            _summarise_laptop(r) for r in results
        ],
    }


def get_laptops_by_brand(
    brand: str,
    min_price: float | None = None,
    max_price: float | None = None,
    sort_by: Literal["price", "ram", "storage"] | None = "price",
    ascending: bool = True,
    limit: int = 20,
) -> dict:
    """Get all laptops from a specific brand, optionally filtered by price.

    Args:
        brand: Brand name (case-insensitive, e.g. "HP", "Asus", "Dell").
        min_price: Minimum price in Rupees.
        max_price: Maximum price in Rupees.
        sort_by: Field to sort by (default: price).
        ascending: Sort ascending (default: True).
        limit: Max results to return (default: 20).

    Returns:
        Matching laptops and brand summary.
    """
    return search_laptops(
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        ascending=ascending,
        limit=limit,
    )


def get_laptops_by_price_range(
    min_price: float,
    max_price: float,
    sort_by: Literal["price", "ram", "storage"] | None = "price",
    ascending: bool = True,
    limit: int = 20,
) -> dict:
    """Find laptops within a specific price range in Rupees.

    Args:
        min_price: Minimum price (e.g. 30000).
        max_price: Maximum price (e.g. 70000).
        sort_by: Field to sort by.
        ascending: Sort ascending (default: True).
        limit: Max results to return.

    Returns:
        Laptops in the price range with the budget category label.
    """
    if min_price > max_price:
        return {
            "status": "error",
            "message": "min_price cannot be greater than max_price.",
        }

    result = search_laptops(
        min_price=min_price,
        max_price=max_price,
        sort_by=sort_by,
        ascending=ascending,
        limit=limit,
    )

    if result["count"] > 0:
        category = _match_budget_category((min_price + max_price) / 2)
        result["budget_category"] = (
            f"Laptops in this range are considered '{category}'."
        )
    return result


def get_laptop_by_model(model: str) -> dict:
    """Look up the full details of a specific laptop by its model name/number.

    Args:
        model: Model name or number to search for (case-insensitive, partial match).

    Returns:
        The full laptop details if found.
    """
    data = _load_data()
    query = model.lower().strip()

    # Try exact match first, then partial
    for row in data:
        if row.get("Model", "").lower().strip() == query:
            return {"status": "success", "laptop": _full_laptop_detail(row)}

    matches = [r for r in data if query in r.get("Model", "").lower()]
    if not matches:
        return {
            "status": "error",
            "message": f"No laptop found matching model '{model}'. Try a different search term.",
        }

    return {
        "status": "success",
        "note": f"Showing {len(matches)} partial match(es).",
        "laptop": _full_laptop_detail(matches[0]),
        "other_matches": [_summarise_laptop(r) for r in matches[1:6]],
    }


def compare_laptops(models: list[str]) -> dict:
    """Compare two or more laptop models side by side.

    Args:
        models: A list of model names/numbers to compare (at least 2, at most 5).

    Returns:
        A side-by-side comparison table.
    """
    if not models or len(models) < 2:
        return {
            "status": "error",
            "message": "Please provide at least two model names to compare.",
        }
    if len(models) > 5:
        return {
            "status": "error",
            "message": "You can compare at most 5 laptops at once.",
        }

    data = _load_data()
    found: list[dict] = []

    # ── Model resolution ───────────────────────────────────────────────────
    # For each user-supplied term we first try an exact (case-insensitive)
    # match on the Model column.  If that fails, fall back to a substring
    # match so that partial model numbers still work.
    for q in models:
        ql = q.lower().strip()
        match = None

        # Attempt exact match first.
        for row in data:
            if row.get("Model", "").lower().strip() == ql:
                match = row
                break

        # Fallback: partial (substring) match.
        if not match:
            for row in data:
                if ql in row.get("Model", "").lower():
                    match = row
                    break

        if match:
            found.append(match)

    # We need at least two matched models for a useful comparison.
    if len(found) < 2:
        return {
            "status": "error",
            "message": f"Could not find enough matching models. Found {len(found)} of {len(models)}.",
        }

    # ── Build comparison table ─────────────────────────────────────────────
    # Pick the most informative / frequently asked-about fields for
    # a side-by-side comparison view.
    comparison_fields = [
        "Brand", "Model", "Series", "Price (Rs)", "Processor",
        "Capacity", "Graphic Processor", "SSD Capacity",
        "Display Size", "Display Resolution", "Display Touchscreen",
        "Weight", "Operating System", "Battery Life",
        "USB Type C", "Backlit Keyboard", "Fingerprint scanner",
        "Warranty",
    ]

    comparison_rows = []
    for laptop in found:
        # Build a human-readable label like "Acer PHN16-71 (NH.QLTSI.002)".
        entry = {
            "name": f"{laptop.get('Brand', '')} {laptop.get('Model', '')}".strip()
        }
        for field in comparison_fields:
            val = laptop.get(field, "").strip()
            # Format the price column nicely with the Rs. prefix and locale grouping.
            if field == "Price (Rs)":
                try:
                    val = f"Rs. {float(val):,.0f}" if val else "N/A"
                except ValueError:
                    val = "N/A"
            entry[field] = val if val else "N/A"
        comparison_rows.append(entry)

    return {
        "status": "success",
        "count": len(comparison_rows),
        "fields": comparison_fields,
        "comparison": comparison_rows,
    }


def get_laptop_recommendations(
    budget_max: float | None = None,
    primary_use: Literal[
        "gaming", "student", "business", "creative",
        "portable", "programming", "general",
    ] = "general",
    preferred_brand: str | None = None,
    min_ram: str | None = None,
    touchscreen: bool | None = None,
    limit: int = 10,
) -> dict:
    """Get smart laptop recommendations tailored to the customer's needs.

    Combines usage intent with budget and preferences to suggest the best
    matching laptops.

    Args:
        budget_max: Maximum budget in Rupees.
        primary_use: What the customer plans to use the laptop for.
        preferred_brand: Optional brand preference.
        min_ram: Minimum RAM required (e.g. "8 GB", "16 GB").
        touchscreen: Whether touchscreen is desired.
        limit: Number of recommendations.

    Returns:
        Tailored recommendations with reasoning.
    """
    data = _load_data()

    # ── Filtering pipeline ─────────────────────────────────────────────────
    # Start by excluding records with no valid price, then progressively
    # narrow the candidate pool.

    # Exclude records with no valid price (data-quality gap).
    data = [r for r in data if r["_price"] > 0]

    # Apply the usage-intent classifier first (this is the primary signal).
    candidates = [r for r in data if _matches_intent(r, primary_use)]

    if budget_max:
        candidates = [r for r in candidates if r["_price"] <= budget_max]

    if preferred_brand:
        candidates = [
            r for r in candidates
            if preferred_brand.lower() in r.get("Brand", "").lower()
        ]

    if min_ram:
        candidates = [
            r for r in candidates
            if _capacity_gte(r.get("Capacity", ""), min_ram)
        ]

    if touchscreen is not None:
        wanted = "Yes" if touchscreen else "No"
        candidates = [
            r for r in candidates
            if r.get("Display Touchscreen", "").strip() == wanted
        ]

    # ── Scoring & ranking ──────────────────────────────────────────────────
    # We compute a simple quality score for each candidate that rewards:
    #   • more RAM (weight 0.5)
    #   • larger SSD (weight 0.3)
    #   • price close to the budget ceiling (better value-for-money)
    def _score(l: dict) -> float:
        s = 0.0
        s += _parse_capacity_gb(l.get("Capacity", "")) * 0.5
        s += _parse_capacity_gb(l.get("SSD Capacity", "")) * 0.3
        if budget_max:
            # Closer to budget (but under) = better value
            ratio = l["_price"] / budget_max
            if ratio <= 0.9:
                s += 10 * ratio  # closer to 90% of budget = more features
        return s

    candidates.sort(key=_score, reverse=True)
    candidates = candidates[:limit]

    if not candidates:
        return {
            "status": "error",
            "message": (
                "No laptops match your criteria. Try increasing your budget, "
                "relaxing the RAM or touchscreen requirement, or choosing a different use case."
            ),
        }

    return {
        "status": "success",
        "primary_use": primary_use,
        "budget_max": budget_max,
        "count": len(candidates),
        "recommendations": [
            {
                **_summarise_laptop(r),
                "why": _recommendation_reason(r, primary_use),
            }
            for r in candidates
        ],
    }


def get_available_brands() -> dict:
    """List all laptop brands available in the catalogue with counts.

    Useful as an initial "what do you have?" query so the agent can help
    customers discover which manufacturers are stocked.

    Returns:
        Sorted list of brands, model counts, and min/max price range per brand.
    """
    data = _load_data()

    # ── Aggregate per brand ────────────────────────────────────────────────
    brand_count: dict[str, int] = {}
    brand_price_range: dict[str, dict] = {}

    for row in data:
        b = row.get("Brand", "").strip()
        if not b:
            continue  # skip rows with missing brand

        brand_count[b] = brand_count.get(b, 0) + 1

        p = row["_price"]
        if b not in brand_price_range:
            brand_price_range[b] = {"min": p, "max": p}
        else:
            brand_price_range[b]["min"] = min(brand_price_range[b]["min"], p)
            brand_price_range[b]["max"] = max(brand_price_range[b]["max"], p)

    # ── Build response ─────────────────────────────────────────────────────
    brands_list = [
        {
            "brand": b,
            "models_available": brand_count[b],
            "price_range_rs": {
                "min": brand_price_range[b]["min"],
                "max": brand_price_range[b]["max"],
            },
        }
        for b in sorted(brand_count.keys())  # alphabetical order
    ]

    return {
        "status": "success",
        "total_brands": len(brands_list),
        "total_models": len(data),
        "brands": brands_list,
    }


# ── Helper Utilities ─────────────────────────────────────────────────────────


def _parse_capacity_gb(raw: str) -> float:
    """Convert a capacity string like ``'512 GB'``, ``'1 TB'``, or ``'16 GB'`` to a float in GB.

    Args:
        raw: Human-readable capacity (e.g. ``"512 GB"``, ``"1 TB"``).

    Returns:
        Capacity in gigabytes, or ``0.0`` if the string cannot be parsed.
    """
    import re
    raw = raw.strip().upper()
    m = re.match(r"([\d.]+)\s*(TB|GB|MB)", raw)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "TB":
        return val * 1024
    elif unit == "MB":
        return val / 1024
    return val


def _capacity_gte(row_val: str, filter_val: str) -> bool:
    """Return ``True`` if *row_val* ≥ *filter_val*, parsing capacities sensibly.

    This lets us compare values like ``"8 GB"`` vs ``"16 GB"`` or
    ``"512 GB"`` vs ``"1 TB"`` without manual unit conversion.

    Args:
        row_val: Capacity from the dataset (e.g. ``"8 GB"``).
        filter_val: User-supplied minimum (e.g. ``"16 GB"``).

    Returns:
        Whether the row meets or exceeds the requested minimum.
    """
    return _parse_capacity_gb(row_val) >= _parse_capacity_gb(filter_val)


def _summarise_laptop(row: dict) -> dict:
    """Return a concise summary of a laptop for use in search-result lists.

    The summary omits niche fields (audio, connectivity, warranty details)
    to keep the response lightweight and scannable.

    Args:
        row: A single laptop record.

    Returns:
        Dict with the most important specs (brand, model, CPU, RAM, storage,
        GPU, display, weight, OS, price).
    """
    return {
        "brand": row.get("Brand", ""),
        "model": row.get("Model", ""),
        "series": row.get("Series", ""),
        "processor": row.get("Processor", ""),
        "ram": row.get("Capacity", ""),
        "storage": row.get("SSD Capacity", ""),
        "gpu": row.get("Graphic Processor", ""),
        "display_size": row.get("Display Size", ""),
        "display_resolution": row.get("Display Resolution", ""),
        "weight": row.get("Weight", ""),
        "os": row.get("Operating System", ""),
        "price_rs": row["_price"],
    }


def _full_laptop_detail(row: dict) -> dict:
    """Return the complete detail record for a single laptop.

    This is used by ``get_laptop_by_model`` and returns every scrap of
    information we have about a laptop, organised into logical groups
    (RAM, storage, graphics, display, etc.) so the agent can answer
    very specific follow-up questions.

    Args:
        row: A single laptop record.

    Returns:
        A deeply nested dict with all available specs.
    """
    return {
        "brand": row.get("Brand", ""),
        "model": row.get("Model", ""),
        "series": row.get("Series", ""),
        "price_rs": row["_price"],
        "processor": row.get("Processor", ""),
        "clock_speed": row.get("Clock-speed", ""),
        "chipset": row.get("Chipset", ""),
        "cache": row.get("Cache", ""),
        "ram": {
            "capacity": row.get("Capacity", ""),
            "type": row.get("RAM Type", ""),
            "speed": row.get("RAM Speed", ""),
            "slots": row.get("Memory Slots", ""),
            "layout": row.get("Memory Layout", ""),
        },
        "storage": {
            "ssd_capacity": row.get("SSD Capacity", ""),
            "ssd_type": row.get("SSD Type", ""),
            "hdd_capacity": row.get("HDD Capacity", ""),
            "hdd_speed": row.get("HDD Speed(RPM)", ""),
            "expandable_memory": row.get("Expandable Memory", ""),
        },
        "graphics": {
            "gpu": row.get("Graphic Processor", ""),
            "memory": row.get("Graphics Memory", ""),
        },
        "display": {
            "size": row.get("Display Size", ""),
            "resolution": row.get("Display Resolution", ""),
            "type": row.get("Display Type", ""),
            "features": row.get("Display Features", ""),
            "touchscreen": row.get("Display Touchscreen", ""),
            "refresh_rate": row.get("Refresh Rate", ""),
            "brightness": row.get("Brightness", ""),
        },
        "physical": {
            "dimensions": row.get("Dimensions (WxDxH)", ""),
            "thickness": row.get("Thickness", ""),
            "weight": row.get("Weight", ""),
            "colors": row.get("Colors", ""),
        },
        "operating_system": {
            "os": row.get("Operating System", ""),
            "os_type": row.get("Operating System Type", ""),
        },
        "battery": {
            "type": row.get("Battery Type", ""),
            "cells": row.get("Battery Cell", ""),
            "battery_life": row.get("Battery Life", ""),
            "capacity": row.get("Battery Capacity", ""),
            "power_supply": row.get("Power Supply", ""),
            "fast_charging": row.get("Fast Charging Support", ""),
        },
        "connectivity": {
            "wireless_lan": row.get("Wireless LAN", ""),
            "wifi_version": row.get("Wi-Fi Version", ""),
            "bluetooth": row.get("Bluetooth", ""),
            "bluetooth_version": row.get("Bluetooth Version", ""),
            "usb_2_0": row.get("USB 2.0 slots", ""),
            "usb_3_0": row.get("USB 3.0 slots", ""),
            "usb_type_c": row.get("USB Type C", ""),
            "hdmi": row.get("HDMI Ports", ""),
            "thunderbolt": row.get("Thunderbolt Port", ""),
            "vga": row.get("VGA Port", ""),
            "ethernet": row.get("Ethernet ports", ""),
        },
        "features": {
            "backlit_keyboard": row.get("Backlit Keyboard", ""),
            "fingerprint_scanner": row.get("Fingerprint scanner", ""),
            "face_recognition": row.get("Face Recognition", ""),
            "sd_card_reader": row.get("SD Card Reader", ""),
            "webcam": row.get("Web-cam", ""),
            "lockport": row.get("Lockport", ""),
            "pointing_device": row.get("Pointing device", ""),
            "keyboard": row.get("Keyboard", ""),
        },
        "audio": {
            "audio_solution": row.get("Audio Solution", ""),
            "speakers": row.get("Speakers", ""),
            "sound_technologies": row.get("Sound Technologies", ""),
            "microphone": row.get("In-built Microphone", ""),
        },
        "warranty": row.get("Warranty", ""),
        "sales_package": row.get("Sales Package", ""),
    }


def _recommendation_reason(row: dict, intent: str) -> str:
    """Generate a human-readable, sales-friendly reason *why* a laptop is being recommended.

    The message is tailored to the usage intent so the agent can explain
    its suggestion in plain language.

    Args:
        row: A single laptop record.
        intent: The usage category the recommendation was made for.

    Returns:
        A sentence fragment (e.g. ``"Dedicated gaming GPU; 16 GB RAM for smooth gaming."``).
    """
    reasons = []
    price = row["_price"]

    if intent == "gaming":
        reasons.append("Dedicated gaming GPU")
        ram = row.get("Capacity", "")
        if ram in ("16 GB", "32 GB", "64 GB"):
            reasons.append(f"{ram} RAM for smooth gaming")
    elif intent == "student":
        reasons.append("Great value for students")
        if price <= 40000:
            reasons.append("Very affordable")
        if row["_weight_kg"] <= 1.8:
            reasons.append("Lightweight and portable for campus")
    elif intent == "business":
        reasons.append("Suitable for professional use")
        if row.get("Battery Life", "").strip():
            reasons.append("Good battery life")
    elif intent == "creative":
        reasons.append("Powerful GPU and RAM for creative workloads")
        display_size = _parse_display_size(row.get("Display Size", ""))
        if display_size >= 15.6:
            reasons.append("Large display for detailed work")
    elif intent == "portable":
        reasons.append(f"Lightweight design ({row['_weight_kg']} kg)")
    elif intent == "programming":
        ram = row.get("Capacity", "")
        reasons.append(f"{ram} RAM for multitasking while coding")
        proc = row.get("Processor", "")
        if "i7" in proc or "i9" in proc or "ryzen 7" in proc.lower() or "ryzen 9" in proc.lower():
            reasons.append("High-performance processor for compilation")

    if not reasons:
        reasons.append("Balanced features at this price point")

    return "; ".join(reasons) + "."
