# VeriFuse Sovereign Vault — Airtable Schema Reference
## Exact Formulas for Copy-Paste into Airtable

---

## TABLE 1: MASTER_ASSETS

### Field: Surplus_Liquidity (Formula, Currency USD)
```
IF(
  AND({Bid_Amount}, {Total_Debt}),
  IF(
    {Bid_Amount} - {Total_Debt} > 0,
    {Bid_Amount} - {Total_Debt},
    0
  ),
  BLANK()
)
```

### Field: Days_Since_Sale (Formula, Integer)
```
IF(
  {Foreclosure_Date},
  DATETIME_DIFF(NOW(), {Foreclosure_Date}, 'days'),
  BLANK()
)
```

### Field: Statute_Status (Formula, Single Line Text)
```
IF(
  OR(NOT({Foreclosure_Date}), NOT({Surplus_Liquidity})),
  "INSUFFICIENT DATA",
  IF(
    {Days_Since_Sale} < 0,
    "SALE NOT YET OCCURRED",
    IF(
      {Days_Since_Sale} <= 180,
      "🟢 ATTORNEY EXCLUSIVE (Unregulated Period)",
      IF(
        {Days_Since_Sale} <= 730,
        "🟡 FINDER ELIGIBLE (20% Cap — C.R.S. 38-38-111)",
        IF(
          {Days_Since_Sale} <= 1825,
          "🟠 STATE TREASURY (10% Cap — RUUPA)",
          "🔴 ESCHEATMENT RISK (>5 Years)"
        )
      )
    )
  )
)
```

### Field: Statute_Window (Formula, Single Line Text)
```
IF(
  {County} = "Palm Beach",
  "Fla. Stat. 45.032 (1yr)",
  IF(
    OR(
      {County} = "Denver",
      {County} = "Jefferson",
      {County} = "Arapahoe",
      {County} = "Adams",
      {County} = "Douglas",
      {County} = "El Paso",
      {County} = "Weld",
      {County} = "Mesa",
      {County} = "Eagle"
    ),
    "C.R.S. 38-38-111 (5yr foreclosure)",
    "UNKNOWN — VERIFY MANUALLY"
  )
)
```

### Field: Days_Remaining (Formula, Integer)
```
IF(
  NOT({Foreclosure_Date}),
  BLANK(),
  IF(
    {County} = "Palm Beach",
    365 - {Days_Since_Sale},
    1825 - {Days_Since_Sale}
  )
)
```

### Field: Fee_Cap_Pct (Formula, Percent)
```
IF(
  NOT({Statute_Status}),
  BLANK(),
  IF(
    {Days_Since_Sale} <= 180,
    0.33,
    IF(
      {Days_Since_Sale} <= 730,
      0.20,
      0.10
    )
  )
)
```

### Field: Estimated_Fee (Formula, Currency USD)
```
IF(
  AND({Surplus_Liquidity}, {Fee_Cap_Pct}),
  {Surplus_Liquidity} * {Fee_Cap_Pct},
  BLANK()
)
```

---

## TABLE 2: INTELLIGENCE_LAYERS

### Field: Equity_Delta (Rollup + Formula)
Use a Rollup on the Asset_Link field to pull Bid_Amount, then:
```
{Zestimate_Value} - {Bid_Amount_Rollup}
```

---

## VIEWS TO CREATE

| View Name | Filter | Sort |
|-----------|--------|------|
| Attorney Exclusive | Statute_Status contains "ATTORNEY EXCLUSIVE" | Days_Since_Sale ASC |
| Finder Eligible | Statute_Status contains "FINDER ELIGIBLE" | Surplus_Liquidity DESC |
| Escheatment Watch | Days_Remaining < 90 | Days_Remaining ASC |
| High Value | Surplus_Liquidity > 25000 | Estimated_Fee DESC |
| Data Quality | Data_Grade = "REJECT" or "BRONZE" | Updated_At DESC |
