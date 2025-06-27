# HueClientRest

A Python REST client for interacting with Hadoop Hue's REST API. This client allows you to execute SQL queries, manage files, and download results through Hue's web interface programmatically.
With support of [Quadient](https://www.quadient.com)

## Features

- **Authentication**: JWT token-based authentication
- **Query Execution**: Execute SQL queries with various dialects (Hive, Spark SQL, etc.)
- **Result Management**: Fetch query results with pagination support
- **File Operations**: List, download, and manage files in remote storage
- **CSV Export**: Save query results directly to CSV files
- **Batch Operations**: Execute queries and download resulting files in one operation

## Installation

```bash
pip install hueclientrest
```

## Quick Start

```python
from hueclientrest import HueClientREST

# Initialize the client
client = HueClientREST(
    host="https://your-hue-server.com",
    username="your_username",
    password="your_password",
    verify_ssl=True
)

# Execute a query and save results to CSV
client.run(
    statement="SELECT * FROM your_table LIMIT 100",
    dialect="hive",
    filename="results.csv"
)
```

## Usage Examples

### Basic Query Execution

```python
from hueclientrest import HueClientREST

client = HueClientREST(
    host="https://your-hue-server.com",
    username="your_username",
    password="your_password"
)

# Simple query execution with CSV output
client.run(
    statement="SELECT count(*) FROM sales WHERE date >= '2023-01-01'",
    dialect="hive",
    filename="sales_count.csv"
)
```

### Advanced Query Execution

```python
# Step-by-step execution for more control
client.login()

# Execute query
operation_id = client.execute(
    statement="SELECT * FROM large_table WHERE condition = 'value'",
    dialect="spark"
)

# Wait for completion
client.wait(operation_id, poll_interval=5, timeout=600)

# Fetch results with custom batch size
headers, rows = client.fetch_all(operation_id, batch_size=5000)

# Save to CSV
client.save_csv(headers, rows, "large_results.csv")
```

### File Operations

```python
# List files in a directory
files = client.list_directory("/user/data/exports")
for file_info in files:
    print(f"Name: {file_info['name']}, Size: {file_info.get('size', 'N/A')}")

# Download a specific file
client.download_file(
    file_path="/user/data/exports/report.csv",
    local_filename="./downloads/report.csv"
)

# Download all files from a directory
downloaded_files = client.download_directory_files(
    directory_path="/user/data/exports",
    local_dir="./downloads",
    file_pattern="part-"  # Only download files containing "part-"
)

# Upload file
response = client.upload('/user/uploads', '.import.csv')

```

### Export Query Results to Files

```python
# Execute INSERT OVERWRITE DIRECTORY and download results
statement = """
INSERT OVERWRITE DIRECTORY '/user/exports/sales_2023'
STORED AS TEXTFILE
SELECT * FROM sales WHERE year = 2023
"""

downloaded_files = client.run_and_download(
    statement=statement,
    directory_path="/user/exports/sales_2023",
    local_dir="./sales_data",
    dialect="hive",
    file_pattern="part-",
    timeout=900  # 15 minutes timeout
)

print(f"Downloaded {len(downloaded_files)} files")
```

### Working with Different SQL Dialects

```python
# Hive query
client.run(
    statement="SHOW TABLES",
    dialect="hive",
    filename="hive_tables.csv"
)

# Spark SQL query
client.run(
    statement="SELECT spark_version()",
    dialect="sparksql",
    filename="spark_version.csv"
)

# Impala query
client.run(
    statement="SELECT version()",
    dialect="impala",
    filename="impala_version.csv"
)
```

### SSL Configuration

```python
# Disable SSL verification (not recommended for production)
client = HueClientREST(
    host="https://your-hue-server.com",
    username="your_username",
    password="your_password",
    verify_ssl=False,
    ssl_warnings=False  # Suppress SSL warnings
)

# Custom SSL verification
client = HueClientREST(
    host="https://your-hue-server.com",
    username="your_username",
    password="your_password",
    verify_ssl=True  # Use system CA bundle
)
```

### Error Handling

```python
from hueclientrest import HueClientREST

client = HueClientREST(
    host="https://your-hue-server.com",
    username="your_username",
    password="your_password"
)

try:
    client.run(
        statement="SELECT * FROM non_existent_table",
        dialect="hive",
        filename="results.csv"
    )
except RuntimeError as e:
    print(f"Authentication or execution error: {e}")
except TimeoutError as e:
    print(f"Query timed out: {e}")
except ValueError as e:
    print(f"Invalid response format: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### Batch Processing

```python
queries = [
    ("SELECT count(*) FROM table1", "table1_count.csv"),
    ("SELECT count(*) FROM table2", "table2_count.csv"),
    ("SELECT count(*) FROM table3", "table3_count.csv"),
]

client = HueClientREST(
    host="https://your-hue-server.com",
    username="your_username",
    password="your_password"
)

# Login once for all queries
client.login()

for query, filename in queries:
    try:
        operation_id = client.execute(query, "hive")
        client.wait(operation_id)
        headers, rows = client.fetch_all(operation_id)
        client.save_csv(headers, rows, filename)
        print(f"Completed: {filename}")
    except Exception as e:
        print(f"Failed {filename}: {e}")
```

## Unit tests

```python

python -m unittest

```

## API Reference

### [`HueClientREST`](src/hueclientrest/core.py)

Main client class for interacting with Hue REST API.

#### Constructor Parameters
- `host` (str): Hue server URL
- `username` (str): Username for authentication
- `password` (str): Password for authentication
- `verify_ssl` (bool): Whether to verify SSL certificates (default: True)
- `ssl_warnings` (bool): Whether to show SSL warnings (default: False)

#### Methods

- [`login()`](src/hueclientrest/core.py): Authenticate and obtain JWT token
- [`execute(statement, dialect)`](src/hueclientrest/core.py): Execute SQL statement
- [`wait(operation_id, poll_interval, timeout)`](src/hueclientrest/core.py): Wait for operation completion
- [`fetch_all(operation_id, batch_size)`](src/hueclientrest/core.py): Fetch all query results
- [`save_csv(headers, rows, filename)`](src/hueclientrest/core.py): Save results to CSV file
- [`run(statement, dialect, filename, batch_size)`](src/hueclientrest/core.py): Execute query and save to CSV
- [`list_directory(directory_path, pagesize)`](src/hueclientrest/core.py): List directory contents
- [`download_file(file_path, local_filename)`](src/hueclientrest/core.py): Download single file
- [`download_directory_files(directory_path, local_dir, file_pattern)`](src/hueclientrest/core.py): Download multiple files
- [`run_and_download(statement, directory_path, local_dir, ...)`](src/hueclientrest/core.py): Execute and download results
- [`check_directory_exists(directory_path)`](src/hueclientrest/core.py): Check if directory exists
- [`upload_file(dest_path, file_path)`](src/hueclientrest/core.py): Upload a file to a directory
## Requirements

- Python 3.7+
- requests
- urllib3

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Support

For issues and questions, please create an issue in the GitHub repository.