-- S3 access for DuckDB: extensions + a credential-chain secret. The AWS SDK
-- default chain resolves credentials (honouring the AWS_PROFILE env var, which
-- loader.connect() defaults to 'swimtrends'), reading ~/.aws/credentials. We do
-- NOT pin PROFILE/CHAIN here: DuckDB's profile resolver only reads ~/.aws/config,
-- but this project's profile lives in ~/.aws/credentials.
INSTALL httpfs;
LOAD httpfs;
INSTALL aws;
LOAD aws;

CREATE SECRET IF NOT EXISTS swimtrends_s3 (
    TYPE s3,
    PROVIDER credential_chain,
    REGION 'eu-west-1'
);

-- Source-binding views over the Spec 2 curated zone. hive_partitioning is OFF:
-- season and course are stored as columns INSIDE each Parquet file as well as in
-- the season=/course= path, so enabling hive partitioning would bind them twice.
CREATE OR REPLACE VIEW cur_obt AS
    SELECT * FROM read_parquet('s3://swimtrends-meet-data/curated/obt_result/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_dim_meet AS
    SELECT * FROM read_parquet('s3://swimtrends-meet-data/curated/dim_meet/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_dim_race AS
    SELECT * FROM read_parquet('s3://swimtrends-meet-data/curated/dim_race/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_fact_result AS
    SELECT * FROM read_parquet('s3://swimtrends-meet-data/curated/fact_result/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_fact_split AS
    SELECT * FROM read_parquet('s3://swimtrends-meet-data/curated/fact_split/**/*.parquet',
        hive_partitioning = false);
