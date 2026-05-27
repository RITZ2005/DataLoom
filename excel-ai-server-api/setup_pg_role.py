import psycopg2
try:
    conn = psycopg2.connect(host='localhost', port=5433, dbname='hybrid', user='postgres', password='pgvector')
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute("CREATE ROLE ai_readonly LOGIN PASSWORD 'readonly_pass'")
        print('Role ai_readonly created')
    except psycopg2.errors.DuplicateObject:
        print('Role ai_readonly already exists')
    cur.execute('GRANT CONNECT ON DATABASE hybrid TO ai_readonly')
    cur.execute('REVOKE ALL ON SCHEMA public FROM ai_readonly')
    cur.execute('GRANT USAGE ON SCHEMA public TO ai_readonly')
    cur.execute('GRANT USAGE ON SCHEMA etl_system TO ai_readonly')
    cur.execute('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ai_readonly')
    cur.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM ai_readonly')
    print('Grants applied')
    conn.close()
except Exception as e:
    print(f"Error: {e}")
