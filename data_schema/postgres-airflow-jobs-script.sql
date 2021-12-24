create table if not exists afj_opensearch_bulk_failed_data
(
    id        serial
        constraint afj_opensearch_bulk_failed_data_pk
            primary key,
    owner     varchar not null,
    repo      varchar not null,
    type      varchar not null,
    bulk_data text    not null
);

create unique index if not exists afj_opensearch_bulk_failed_data_id_uindex
    on afj_opensearch_bulk_failed_data (id);

create index if not exists afj_opensearch_bulk_failed_data__index_owner_repo
    on afj_opensearch_bulk_failed_data (owner, repo);

create index if not exists afj_opensearch_bulk_failed_data__index_type
    on afj_opensearch_bulk_failed_data (type);

