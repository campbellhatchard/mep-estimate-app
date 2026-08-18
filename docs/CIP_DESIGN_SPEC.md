# CIP Integration Design — v0.3.0

## Baseline and release intent

This build is based on the locked `baseline/v0.2.1-locked` MEP release. MEP calculation behavior is retained as the MEP implementation. CIP is introduced as a second product domain behind a product selection step.

## Product selection

`New Estimate` presents two immutable choices:

- Mobile Enterprise Platform (MEP)
- Cloud Inventory Platform (CIP)

The estimate number is allocated only after a product is selected. Both products use the shared `YYYYMMNNN` monthly sequence.

Legacy estimates with no `estimate_products` companion record are interpreted as MEP. New estimates create an explicit product record.

## Isolation model

The v0.3.0 architecture deliberately avoids adding CIP conditionals to the locked MEP calculation engine.

Shared:
- authentication and multi-role users
- estimate repository and numbering
- estimate lifecycle
- audit
- schedule persistence/editing
- PDF/Jira framework
- database and Render deployment

Independent:
- active configuration version
- product-specific input model
- scope catalog
- calculation engine
- detail/testing calculations
- schedule generation source

`configuration_products` allows one active MEP model and one active CIP model simultaneously. Activating a CIP draft retires only the prior CIP configuration; it cannot retire the active MEP model.

## CIP data model

Companion tables avoid rewriting the locked MEP schema:

- `estimate_products`
- `configuration_products`
- `cip_revision_inputs`
- `cip_scope_items`
- `cip_nonbillable_allocations`

CIP scope categories:
- DESKTOP
- CUSTOM_DESKTOP
- MOBILE
- CUSTOM_MOBILE
- INTEGRATION
- REPORT
- LABEL
- CUSTOM_BOOMI
- REST

## CIP software releases

Initial active releases:
- Release 25.2
- Release 25.3
- Release 26.1
- Release 26.2

The highest active release rank is the default for a new CIP estimate, so the initial default is Release 26.2.

An Administrator can add a release to a Draft CIP calculation model. The current latest Desktop, Mobile, and Integration catalogs are cloned into the new release and can then be changed before activation.

## CIP calculation output

Every CIP calculation returns:
- development detail
- solution testing detail
- phase calculation lines
- Investment Hours
- Plan Hours Not Billable
- total internal task effort
- fees
- estimate range
- duration

Investment Hours are customer-billed hours. Plan Hours Not Billable are additional internal effort and do not increase customer fees.

## CIP testing

CIP testing is independent from MEP unit testing.

Project-wide factors:
- Inventory / Inbound & Outbound Handling Units
- Lot / Serial Control
- Food / Pharma
- Location Dimension
- Setup Customer Test Data
- Monitored Session

Component methodologies:
- Desktop standard
- Custom Desktop
- Mobile standard
- Custom Mobile
- Reporting
- Labels
- Baseline integrations
- Custom Boomi integrations
- RESTful interfaces

The intentional 10x difference between Desktop and Mobile baseline small-change test factors is retained:
- Desktop: 0.50
- Mobile: 0.05

## Schedule

CIP uses the shared editable `schedule_tasks` model but its generated schedule comes from CIP calculation lines. MEP continues to use its locked workbook-derived schedule template.

## Release gate

v0.3.0 must not be considered production-approved until:
1. all locked MEP regression tests pass,
2. CIP workbook golden scenarios pass,
3. migrations pass from an empty database,
4. product/configuration isolation is verified,
5. user acceptance testing is completed on a non-production deployment.
