# Power BI Report – Business Documentation

## 1. Project Overview

This Power BI project is built around an **Online Sales / Customer Adoption and Retention** dataset. The data model is centered on a table called **OnlineSales**, which holds order, engagement, and customer behavior data (emails sent, open/click rates, order frequency, paperless adoption, refill and doorstep delivery usage, favorite order day, and city).

Based on the tables, measures, and naming patterns present, the business objective of this report appears to be to help stakeholders understand:
- **Customer retention and churn** (e.g., measures named "Retention %," "Churn Rate," "Retained Customers")
- **Customer engagement with digital/service programs** (e.g., "Paperless %," "Refill %," "Doorstep %," email open/click rates)
- **Customer tenure and order behavior** (e.g., "Avg Tenure," "Total Orders," "Avg Order Frequency")

**Note:** No report page or visual information was found in the extracted data, so the specific pages, visuals, and navigation of the finished report cannot be described from this data (see Sections 5–7 and 11 for details). This documentation focuses on what the data model (tables, columns, relationships, and measures) tells us about the report's intended purpose.

---

## 2. Data Tables

| Table Name | Type | Business Purpose | Key Information |
|---|---|---|---|
| Adoption | Helper/Parameter table | Appears to let users switch between different "adoption" metrics in a visual | Adoption, Adoption Fields, Adoption Order |
| DateTableTemplate_efc47e72-c467-4105-9323-0e1ae5ee6ec4 | Technical/auto-generated date table | Power BI system table supporting date hierarchies | Date, Year, Month, Quarter, Day |
| DimCity | Dimension | Stores city names for location analysis | city |
| DimCustomer | Dimension | Stores customer-level details, order dates, and tenure | custid, First Order Date, Last Order Date, Tenure (Days), Tenure Category |
| DimDate | Dimension (Date) | Calendar table for date-based analysis and filtering | Date, Year, Month, Month Number, Quarter, Weekday |
| LocalDateTable_3580b12a-... | Technical/auto-generated date table | Supports date hierarchy for OnlineSales[created] | Date, Year, Month, Quarter, Day |
| LocalDateTable_3eccdf63-... | Technical/auto-generated date table | Supports date hierarchy for DimCustomer[Last Order Date] | Date, Year, Month, Quarter, Day |
| LocalDateTable_59525896-... | Technical/auto-generated date table | Supports date hierarchy for DimCustomer[First Order Date] | Date, Year, Month, Quarter, Day |
| LocalDateTable_78e50cf4-... | Technical/auto-generated date table | Supports date hierarchy for OnlineSales[lastorder] | Date, Year, Month, Quarter, Day |
| Measure | Measures-only table | Container that organizes most business KPIs/measures | No data columns of business relevance; hosts calculations |
| OnlineSales | Fact table | Central table holding order and customer engagement data | custid, retained, created, firstorder, lastorder, esent, eopenrate, eclickrate, avgorder, ordfreq, paperless, refill, doorstep, favday, city |

### Adoption
**Purpose:** Based on its column names (Adoption, Adoption Fields, Adoption Order), this table looks like a small helper table used to let a report user pick which "adoption" style metric (e.g., Paperless %, Refill %, Doorstep %) to display in a chart. This is a common Power BI design pattern, though the exact way it is used in a visual cannot be confirmed from the data provided.
**Important Columns:** Adoption, Adoption Fields, Adoption Order.
**Relationships:** None found in the data model — this table is not connected to any other table via a relationship.
**Business Explanation:** Likely used behind the scenes to give business users flexibility to switch between related adoption metrics without needing multiple charts.

### DateTableTemplate_efc47e72-c467-4105-9323-0e1ae5ee6ec4
**Purpose:** This is a technical table automatically created by Power BI to support built-in date hierarchies (Year/Quarter/Month/Day). It is not meant to be used directly by business users.
**Important Columns:** Date, Year, MonthNo, Month, QuarterNo, Quarter, Day.
**Relationships:** None found in the data model — it does not appear connected to other tables in the relationships list, suggesting it may be an unused system artifact.
**Business Explanation:** No direct business meaning; it's infrastructure Power BI uses internally.

### DimCity
**Purpose:** Provides a list of cities so that sales/order data can be grouped or filtered by location.
**Important Columns:** city.
**Relationships:** Connected to OnlineSales (OnlineSales[city] → DimCity[city]).
**Business Explanation:** Lets business users answer questions like "Which city has the most orders/engagement?"

### DimCustomer
**Purpose:** Holds one row per customer along with their order history dates and how long they've been a customer (tenure).
**Important Columns:** custid, First Order Date, Last Order Date, Tenure (Days), Tenure Category (a calculated grouping of tenure, e.g., short/medium/long-term customers — exact categories not visible in the data).
**Relationships:** Connected to OnlineSales (OnlineSales[custid] → DimCustomer[custid]); also connects onward to two auto-generated date tables via First Order Date and Last Order Date.
**Business Explanation:** Central to understanding customer loyalty, how long people have stayed customers, and when they first/last ordered.

### DimDate
**Purpose:** A calendar reference table for date-based reporting (Year, Quarter, Month, Weekday).
**Important Columns:** Date, Year, Month, Month Number, Quarter, Weekday.
**Relationships:** Connected to OnlineSales (OnlineSales[firstorder] → DimDate[Date]).
**Business Explanation:** Supports trend analysis by calendar period (e.g., orders by quarter/year), specifically tied to when customers placed their first order.

### LocalDateTable_3580b12a-abbe-4493-bc6d-2e319e95633c
**Purpose:** Auto-generated date table supporting the "created" date field in OnlineSales.
**Important Columns:** Date, Year, Month, Quarter, Day (all system-generated).
**Relationships:** Connected to OnlineSales (OnlineSales[created] → this table's Date).
**Business Explanation:** Allows filtering/analysis by the date an order record was created; created automatically by Power BI rather than manually designed.

### LocalDateTable_3eccdf63-f967-4cae-a479-0890081de625
**Purpose:** Auto-generated date table supporting DimCustomer's "Last Order Date" field.
**Important Columns:** Date, Year, Month, Quarter, Day.
**Relationships:** Connected to DimCustomer (DimCustomer[Last Order Date] → this table's Date).
**Business Explanation:** Enables date-based analysis of customers' most recent orders.

### LocalDateTable_59525896-9bd2-4ea0-a9f5-c3005fc4eb12
**Purpose:** Auto-generated date table supporting DimCustomer's "First Order Date" field.
**Important Columns:** Date, Year, Month, Quarter, Day.
**Relationships:** Connected to DimCustomer (DimCustomer[First Order Date] → this table's Date).
**Business Explanation:** Enables date-based analysis of when customers first ordered.

### LocalDateTable_78e50cf4-ef51-4043-9751-7e125699bcd1
**Purpose:** Auto-generated date table supporting OnlineSales' "lastorder" field.
**Important Columns:** Date, Year, Month, Quarter, Day.
**Relationships:** Connected to OnlineSales (OnlineSales[lastorder] → this table's Date).
**Business Explanation:** Enables date-based analysis of customers' most recent order transaction dates.

### Measure
**Purpose:** This table does not hold real business data; it exists purely as a container to organize many of the report's key calculations (measures) in one place.
**Important Columns:** Column (a generic placeholder column, not used for reporting).
**Relationships:** None — a measures-only table is not connected to other tables because it doesn't need to be; its measures reference columns in other tables directly.
**Business Explanation:** Think of this as a "folder" for KPIs like Retention %, Churn Rate, Avg Tenure, etc., making the model easier to manage.

### OnlineSales
**Purpose:** The core transactional/behavioral table capturing each customer's order and engagement activity.
**Important Columns:** custid (customer ID), retained (retention flag), created, firstorder, lastorder (order dates), esent/eopenrate/eclickrate (email engagement), avgorder, ordfreq (order size/frequency), paperless, refill, doorstep (service adoption flags), favday (favorite order day), city.
**Relationships:** Connects to DimCity (city), DimCustomer (custid), DimDate (firstorder), and two auto-generated date tables (created, lastorder).
**Business Explanation:** This is the main data source most KPIs are built from — it tells the story of what customers ordered, how they engage with emails, and which service features (paperless, refill, doorstep) they use.

---

## 3. Data Model

| From Table | Column | To Table | Column | Relationship |
|---|---|---|---|---|
| OnlineSales | created | LocalDateTable_3580b12a-abbe-4493-bc6d-2e319e95633c | Date | Many-to-one (active) |
| OnlineSales | lastorder | LocalDateTable_78e50cf4-ef51-4043-9751-7e125699bcd1 | Date | Many-to-one (active) |
| OnlineSales | city | DimCity | city | Many-to-one (active) |
| OnlineSales | firstorder | DimDate | Date | Many-to-one (active) |
| OnlineSales | custid | DimCustomer | custid | Many-to-one (active) |
| DimCustomer | First Order Date | LocalDateTable_59525896-9bd2-4ea0-a9f5-c3005fc4eb12 | Date | Many-to-one (active) |
| DimCustomer | Last Order Date | LocalDateTable_3eccdf63-f967-4cae-a479-0890081de625 | Date | Many-to-one (active) |

**Simple Explanation:** **OnlineSales** is the main (fact) table — it contains the actual transactional and behavioral data. It connects out to smaller reference (dimension) tables: **DimCity** (locations), **DimCustomer** (customer details), and **DimDate** plus several auto-generated date tables (for different date fields like created, lastorder). **DimCustomer** itself branches out further to two more auto-generated date tables to track first and last order dates at the customer level. This results in a star-like structure with OnlineSales at the center, but with several separate date tables because different date columns (created, firstorder, lastorder, First/Last Order Date) each needed their own date reference rather than sharing a single calendar table. The **Adoption**, **Measure**, and **DateTableTemplate** tables stand alone with no relationships — they support calculations or user selections rather than direct data linking.

---

## 4. DAX Measures

| Measure | Category | Business Definition | Used For |
|---|---|---|---|
| Avg Click Rate | Email Engagement | Average email click rate across orders | Measuring how often customers click on marketing emails |
| Avg Doorstep | Service Adoption | Average use of doorstep delivery service | Tracking doorstep delivery adoption |
| Avg Open Rate | Email Engagement | Average email open rate across orders | Measuring email engagement effectiveness |
| Avg Order Frequency | Order Behavior | Average order size/frequency value | Understanding typical ordering patterns |
| Avg Pages Viewed | Service Adoption | Average "paperless" usage value | Tracking paperless billing/service adoption |
| Avg Refill Rate | Service Adoption | Average refill service usage | Tracking refill program adoption |
| Avg Tenure | Customer Loyalty | Average number of days customers have been active | Understanding customer lifespan |
| Churn Rate | Retention | Percentage of customers who have stopped being active (formula not available in data) | Measuring customer loss |
| Doorstep % | Service Adoption | Percentage of customers using doorstep delivery (formula not available in data) | Adoption tracking |
| Orders per Email Sent | Marketing Effectiveness | Ratio of orders generated per email sent (formula not available in data) | Measuring email campaign ROI |
| Paperless % | Service Adoption | Percentage of customers using paperless billing (formula not available in data) | Adoption tracking |
| Refill % | Service Adoption | Percentage of customers using refill service (formula not available in data) | Adoption tracking |
| Retained Customers | Retention | Count/percentage of retained customers (formula not resolvable — placeholder text in data) | Retention tracking |
| Retention % | Retention | Percentage of customers retained (formula not available in data) | Key retention KPI |
| Tenure Days | Customer Loyalty | Number of days a customer has been active (formula not available in data) | Loyalty analysis |
| Total Customers | Customer Base | Distinct count of customers | Measuring customer base size |
| Total Emails Sent | Marketing Effectiveness | Sum of all emails sent | Marketing volume tracking |
| Avg Order Size % | Order Behavior | Percentage-based average order size measure (form