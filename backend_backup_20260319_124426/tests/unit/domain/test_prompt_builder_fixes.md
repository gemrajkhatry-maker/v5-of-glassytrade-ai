# Prompt Builder Fixes Unit Test Cases

## Test File

`test_prompt_builder_fixes.py`

## Test Purpose

Validate three critical fixes in `prompt_builder.py`:
1. **Profile shape extraction** -- Previously `profile_shape.lower() == "P"` never matched because `profile_shape` is a descriptive string like `"P-shape (top-heavy...)"`. The fix uses `profile_shape[0]` to extract the single-char code.
2. **CVD magnitude and warnings** -- Now shows explicit magnitude values and "DO NOT LONG/SHORT" warnings for extreme CVD slope values.
3. **Decision rules** -- Strengthened with explicit directional prohibitions in the RULES section.

## Test Cases Overview

| Case ID | Feature Description                                        | Test Type     |
| ------- | ---------------------------------------------------------- | ------------- |
| PB-01   | P-shape profile extracted and AVOID LONG warning present   | Positive Test |
| PB-02   | b-shape profile extracted and AVOID SHORT warning present  | Positive Test |
| PB-03   | D-shape profile produces balanced rotation text            | Positive Test |
| PB-04   | B-shape bimodal profile produces breakout text             | Positive Test |
| PB-05   | Empty profile shape produces no profile text               | Negative Test |
| PB-06   | Extreme negative CVD slope triggers DO NOT LONG            | Positive Test |
| PB-07   | Extreme positive CVD slope triggers DO NOT SHORT           | Positive Test |
| PB-08   | Moderate positive CVD slope shows "CVD up" without warning | Positive Test |
| PB-09   | Moderate negative CVD slope shows "CVD down" without warn  | Positive Test |
| PB-10   | BEARISH_DIV divergence triggers DO NOT go LONG             | Positive Test |
| PB-11   | BULLISH_DIV divergence triggers DO NOT go SHORT            | Positive Test |
| PB-12   | Decision rules contain explicit P-shape prohibition        | Positive Test |
| PB-13   | Decision rules contain explicit b-shape prohibition        | Positive Test |
| PB-14   | Decision rules contain CVD directional prohibition         | Positive Test |

## Detailed Test Steps

### PB-01: P-shape Profile Extraction

**Test Purpose**: Verify that a full descriptive P-shape string is correctly recognized and produces the "AVOID LONG" advisory.

**Test Data Preparation**:
- Base market data dict with `profile_shape="P-shape (top-heavy, distribution)"`

**Test Steps**:
1. Call `build_entry_prompt()` with profile_shape set to a full descriptive string
2. Check the returned prompt for "P-shape" text
3. Check the returned prompt for "AVOID LONG" text

**Expected Results**:
- Prompt contains "P-shape"
- Prompt contains "AVOID LONG"

### PB-02: b-shape Profile Extraction

**Test Purpose**: Verify b-shape string is correctly extracted (lowercase 'b') and produces "AVOID SHORT".

**Test Data Preparation**:
- Base market data dict with `profile_shape="b-shape (bottom-heavy)"`

**Test Steps**:
1. Call `build_entry_prompt()` with the b-shape descriptor
2. Check for "b-shape" in the prompt
3. Check for "AVOID SHORT" in the prompt

**Expected Results**:
- Prompt contains "b-shape"
- Prompt contains "AVOID SHORT"

### PB-03: D-shape Balanced Profile

**Test Purpose**: Verify D-shape produces "balanced rotation" text without any directional prohibition.

**Test Data Preparation**:
- Base market data dict with `profile_shape="D"`

**Test Steps**:
1. Call `build_entry_prompt()` with profile_shape="D"
2. Check for "D-shape" text
3. Verify no "AVOID" text appears in the profile section

**Expected Results**:
- Prompt contains "D-shape"
- Prompt contains "balanced rotation"

### PB-04: B-shape Bimodal Profile

**Test Purpose**: Verify B-shape (capital B) produces bimodal/breakout text.

**Test Data Preparation**:
- Base market data dict with `profile_shape="B-shape bimodal"`

**Test Steps**:
1. Call `build_entry_prompt()` with profile_shape starting with "B"
2. Check for "B-shape" and "bimodal" text

**Expected Results**:
- Prompt contains "B-shape"
- Prompt contains "bimodal"

### PB-05: Empty Profile Shape

**Test Purpose**: Verify empty string produces no profile shape output (no crash, no spurious text).

**Test Data Preparation**:
- Base market data dict with `profile_shape=""`

**Test Steps**:
1. Call `build_entry_prompt()` with empty profile_shape
2. Verify none of the shape keywords appear in the prompt

**Expected Results**:
- Prompt does NOT contain "P-shape", "b-shape", "D-shape", or "B-shape"

### PB-06: Extreme Negative CVD Slope

**Test Purpose**: Verify CVD slope < -100 triggers "CVD EXTREME SELLING" and "DO NOT LONG".

**Test Data Preparation**:
- Base market data dict with `cvd_slope=-611`

**Test Steps**:
1. Call `build_entry_prompt()` with extreme negative CVD
2. Check for "CVD EXTREME SELLING" text
3. Check for "DO NOT LONG" text

**Expected Results**:
- Prompt contains "CVD EXTREME SELLING"
- Prompt contains "DO NOT LONG"

### PB-07: Extreme Positive CVD Slope

**Test Purpose**: Verify CVD slope > 100 triggers "CVD EXTREME BUYING" and "DO NOT SHORT".

**Test Data Preparation**:
- Base market data dict with `cvd_slope=200`

**Test Steps**:
1. Call `build_entry_prompt()` with extreme positive CVD
2. Check for "CVD EXTREME BUYING" text
3. Check for "DO NOT SHORT" text

**Expected Results**:
- Prompt contains "CVD EXTREME BUYING"
- Prompt contains "DO NOT SHORT"

### PB-08: Moderate Positive CVD Slope

**Test Purpose**: Verify moderate positive CVD slope shows "CVD up" without "DO NOT" warnings.

**Test Data Preparation**:
- Base market data dict with `cvd_slope=5.0`

**Test Steps**:
1. Call `build_entry_prompt()` with moderate positive CVD
2. Check for "CVD up" text
3. Verify "DO NOT" does NOT appear in CVD context

**Expected Results**:
- Prompt contains "CVD up"
- Prompt does NOT contain "DO NOT LONG" or "DO NOT SHORT" from CVD lines

### PB-09: Moderate Negative CVD Slope

**Test Purpose**: Verify moderate negative CVD slope shows "CVD down" without "DO NOT" warnings.

**Test Data Preparation**:
- Base market data dict with `cvd_slope=-3.0`

**Test Steps**:
1. Call `build_entry_prompt()` with moderate negative CVD
2. Check for "CVD down" text
3. Verify "DO NOT" does NOT appear in CVD lines

**Expected Results**:
- Prompt contains "CVD down"
- No CVD-specific "DO NOT" warnings

### PB-10: BEARISH_DIV Divergence

**Test Purpose**: Verify bearish divergence produces "DO NOT go LONG".

**Test Data Preparation**:
- Base market data dict with `cvd_divergence="BEARISH_DIV"`

**Test Steps**:
1. Call `build_entry_prompt()` with BEARISH_DIV
2. Check for "DO NOT go LONG" text

**Expected Results**:
- Prompt contains "DO NOT go LONG"

### PB-11: BULLISH_DIV Divergence

**Test Purpose**: Verify bullish divergence produces "DO NOT go SHORT".

**Test Data Preparation**:
- Base market data dict with `cvd_divergence="BULLISH_DIV"`

**Test Steps**:
1. Call `build_entry_prompt()` with BULLISH_DIV
2. Check for "DO NOT go SHORT" text

**Expected Results**:
- Prompt contains "DO NOT go SHORT"

### PB-12, PB-13, PB-14: Decision Rules Prohibitions

**Test Purpose**: Verify the RULES section of any prompt contains explicit directional prohibitions for P-shape, b-shape, and CVD.

**Test Steps**:
1. Call `build_entry_prompt()` with minimal data
2. Check RULES text for "P-shape" prohibition
3. Check RULES text for "b-shape" prohibition
4. Check RULES text for CVD prohibition

**Expected Results**:
- RULES section contains "DO NOT go LONG" for P-shape
- RULES section contains "DO NOT go SHORT" for b-shape
- RULES section contains "DO NOT go LONG" and "DO NOT go SHORT" for CVD

## Test Considerations

### Mock Strategy
No mocks needed. `build_entry_prompt()` is a pure function (stateless, no I/O). The only side effect is reading `settings.ALLOW_SHORT` which defaults to False (BUY-only mode).

### Boundary Conditions
- Empty profile_shape string (no crash on indexing `""[0]`)
- CVD slope at exact threshold boundaries (100, -100)
- Combination of CVD divergence + extreme slope (both warnings should appear)

### Asynchronous Operations
None. All functions under test are synchronous.
