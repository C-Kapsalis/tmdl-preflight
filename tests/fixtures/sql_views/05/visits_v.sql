{{ config(materialized='view') }}
select * from {{ source('warehouse', 'visits_base_n') }}
