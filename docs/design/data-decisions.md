# Data decisions

Brief sections 6, 10 and 13. These decisions are applied by the seed script (a later step).
All figures below were measured on `data/northwind/northwind.sql`.

## Source data facts

| Fact | Value |
| --- | --- |
| Orders | 830 (2,155 order lines), 91 customers, 77 products |
| `orders.order_date` | 1996-07-04 to 1998-05-06 |
| `orders.shipped_date` | 1996-07-10 to 1998-05-06; 21 orders not shipped |
| Last month in the data | May 1998, partial (14 orders, ends on the 6th) |
| Customer countries | 21, all in Europe (54 customers) or the Americas (37) |

## 1. Date shift: +27 whole years

Every date column is moved forward by exactly 27 years:

| Table | Columns |
| --- | --- |
| `orders` | `order_date`, `required_date`, `shipped_date` |
| `employees` | `birth_date`, `hire_date` |

Result: orders cover **2023-07-04 to 2025-05-06**.

Implementation: `column + INTERVAL '27 years'`. PostgreSQL maps 29 February to
28 February when the target year is not a leap year. The seed records the shift in
`analytics.data_setup` in the same transaction, so it is applied exactly once (see
`docs/data-setup.md`).

Why whole years:
- Months, quarters and seasonality stay exactly as in the source, so "last quarter"
  compares like with like.
- The shift is easy to explain and to reverse (`- INTERVAL '27 years'`).

Rejected:
- **27 years plus some months** (so data reaches December 2025): breaks the alignment of
  quarters and seasons with the source data.
- **28 years**: data would run to May 2026, past the reference date, so "future" orders
  would exist.

## 2. Business reference date ("business today"): 2025-05-06

The reference date is the last order date after the shift. It will live in versioned
config (`config/`), not in code, and the evaluation uses the same value.

The brief's 2025-12-31 is an example only. With a whole-year shift it would leave
May to December 2025 without data, so "last quarter" and "last month" would return
nothing.

Key calendar rules (the full list is in `docs/business-calendar.md`):

| Term | Rule | Resolves to on 2025-05-06 |
| --- | --- | --- |
| this month / quarter / year | period containing business today, up to business today | May 2025 (1-6 May); Q2 2025 (1 Apr - 6 May); 2025 (1 Jan - 6 May) |
| last month / quarter / year | most recent **complete** period before the current one | April 2025; Q1 2025 (1 Jan - 31 Mar); 2024 |
| the quarter before (last quarter) | the complete period before "last" | Q4 2024 |
| Fiscal year | equals calendar year | |
| Week start | Monday | |
| Time zone | dates only, no time component (UTC) | |

The answer always states the resolved range, for example "Last quarter = 1 Jan to
31 Mar 2025."

## 3. Country-to-region mapping

Region is assigned by the **customer's country**. An order belongs to its customer's region
(not to `ship_country`).

| Region code | Name | Countries | Customers |
| --- | --- | --- | --- |
| `EUROPE` | Europe | Austria, Belgium, Denmark, Finland, France, Germany, Ireland, Italy, Norway, Poland, Portugal, Spain, Sweden, Switzerland, UK | 54 |
| `AMERICAS` | Americas | USA, Canada, Mexico | 21 |
| `ROW` | Rest of World | Brazil, Argentina, Venezuela | 16 |

Why this split: Northwind has no customers outside Europe and the Americas. A pure
continent mapping would leave `sales.other` with no data, and an empty region cannot prove
isolation. Moving the three South American countries into "Rest of World" is a documented,
fictional business rule that gives every regional test user real data.

Rejected:
- **Continent mapping with an empty Rest of World**: proves nothing about isolation.
- **Adding fictional customers**: changes the public dataset and its expected results.

Safety rules:
- The mapping lives in a table (`analytics.country_region`), not in code.
- A country with no mapping belongs to no region, so sales managers see nothing for it
  (fail closed). The seed script checks that every customer country is mapped.
- `customers.region` (state or province) and the `region` table (US territory regions) are
  unrelated Northwind columns. The semantic layer calls our concept "sales region" to
  avoid confusion.
