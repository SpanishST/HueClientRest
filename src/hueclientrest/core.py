import os
import time
import csv
import json
import requests
import urllib3
from urllib.parse import quote
from typing import List, Optional, Dict, Any

class HueClientREST:
    def __init__(self, host: str, username: str, password: str, verify_ssl: bool = True, ssl_warnings: bool = False):
        
        if not verify_ssl and not ssl_warnings:
            # Disable SSL warnings if not verifying SSL
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        if not host or not isinstance(host, str):
            raise ValueError("Host must be a non-empty string.")
        
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.token = None
        self.session = requests.Session()
        self.session.verify = verify_ssl

    def login(self):
        """
            Get JWT token via /api/v1/token/auth/
            Raises:
                RuntimeError: If authentication fails or no token is returned.
        """
        url = f"{self.host}/api/v1/token/auth/"
        payload = {"username": self.username, "password": self.password}
        
        resp = self.session.post(url, data=payload)
        
        if resp.status_code != 200:
            raise RuntimeError(f"Auth failed: {resp.status_code} – {resp.text}")
        
        data = resp.json()
        self.token = data.get("access")
        
        if not self.token:
            raise RuntimeError("No token found.")
        
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def execute(self, statement: str, dialect: str = "hive") -> str:
        """
        Execute query and get operation ID (history_uuid)
        Raises:
            RuntimeError: If the request fails or no operation ID is returned.
        Args:
            statement (str): The SQL statement to execute.
            dialect (str): The SQL dialect to use (default is "hive").
        Returns:
            str: The operation ID (history_uuid) for the executed statement.
        """
        
        url = f"{self.host}/api/v1/editor/execute/{dialect}"
        resp = self.session.post(url, data={"statement": statement})
        resp.raise_for_status()
        js = resp.json()
        
        opid = js.get("history_uuid") or js.get("history_id")
        
        if not opid:
            raise RuntimeError(f"Échec execute: réponse inattendue : {js}")
        
        return opid

    def wait(self, operation_id: str, poll_interval: int = 2, timeout: int = 300):
        """
        Wait for the operation to complete by polling the status endpoint.
        Raises:
            TimeoutError: If the operation does not complete within the specified timeout.
            RuntimeError: If the operation fails with a status like 'failed', 'expired', or 'canceled'.
        Args:
            operation_id (str): The ID of the operation to check.
            poll_interval (int): The interval in seconds to wait between status checks (default is 2).
            timeout (int): The maximum time in seconds to wait for the operation to complete (default is 300).
        Returns:
            None: If the operation completes successfully and results are available.
        """
        url = f"{self.host}/api/v1/editor/check_status"
        waited = 0

        while waited < timeout:
            r = self.session.post(url, data={"operationId": operation_id})
            r.raise_for_status()
            status = r.json().get("query_status", {}).get("status")
            
            if status == "available":
                return
            elif status in {"running", "submitted", "starting", "waiting"}:
                time.sleep(poll_interval)
                waited += poll_interval
            elif status in {"failed", "expired", "canceled"}:
                raise RuntimeError(f"Request failed with status : {status}")
            else:
                time.sleep(poll_interval)
                waited += poll_interval

        raise TimeoutError("Timeout exceeded while waiting for operation to complete.")

    def fetch_all(self, operation_id: str, batch_size: int = 1000, check_interval: int = 2) -> tuple[List[str], List[List]]:
        """
        Get all results for the given operation ID.
        Args:
            operation_id (str): The ID of the operation to fetch results for.
            batch_size (int): Number of rows to fetch per request (default is 1000).
            check_interval (int): Interval in seconds to check if results are available (default is 2).
            timeout (int): Maximum time in seconds to wait for results to be available (default is 300).
        Returns:
            tuple[List[str], List[List]]: A tuple containing (headers, rows)
        """
        url = f"{self.host}/api/v1/editor/fetch_result_data"
                
        all_rows = []
        headers = None
        start_row = 0
        has_more = True
        first_fetch = True
        
        while has_more:
            payload = {
                "operationId": operation_id,
                "startRow": start_row,
                "rows": batch_size
            }
                        
            r = self.session.post(url, data=payload)
            r.raise_for_status()
            js = r.json()
                        
            status = js.get("status")
            
            if status == -1:
                if first_fetch:
                    time.sleep(check_interval)
                    continue
                else:
                    # Plus de données disponibles
                    break
            elif status != 0:
                raise ValueError(f"Unexpected Status : {status}, message: {js.get('message', 'N/A')}")
            
            # extract data
            result = js.get("result", {})
            
            raw_data = result.get("data", [])
            
            # if raw_data is string, try to parse it as JSON or CSV/TSV
            if isinstance(raw_data, str):
                try:
                    rows = json.loads(raw_data)
                except json.JSONDecodeError:
                    # try to divide per line
                    lines = raw_data.strip().split('\n')
                    if len(lines) > 1:
                        # Probable format CSV/TSV
                        rows = []
                        for line in lines:
                            if '\t' in line:
                                rows.append(line.split('\t'))
                            else:
                                rows.append(line.split(','))
                    else:
                        raise ValueError(f"Unexpected single-line string data: {raw_data}")
            else:
                rows = raw_data
            
            # Get the headers from first call
            if first_fetch and headers is None:
                meta = result.get("meta", [])
                if meta and isinstance(meta, list):
                    headers = [col.get("name", f"col_{i}") if isinstance(col, dict) else str(col) for i, col in enumerate(meta)]
                else:
                    columns = result.get("columns", [])
                    if columns:
                        headers = [col.get("name", f"col_{i}") if isinstance(col, dict) else str(col) for i, col in enumerate(columns)]
                    else:
                        if rows and len(rows) > 0:
                            headers = [f"col_{i}" for i in range(len(rows[0]) if isinstance(rows[0], list) else 1)]
                        else:
                            headers = []
            
            if rows and len(rows) > 0:
                all_rows.extend(rows)
            
            # check if there are more rows to fetch
            has_more = result.get("has_more", False) and len(rows) == batch_size
            start_row += len(rows)
            first_fetch = False
            
            if not rows:
                break
        
        return headers or [], all_rows

    def save_csv(self, headers: List[str], rows: List[List], filename: str = "results.csv"):
        """
        Save the fetched rows to a CSV file with headers.
        Args:
            headers (List[str]): The column headers.
            rows (List[List]): The rows to save.
            filename (str): The name of the file to save the results to (default is "results.csv").
        """
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Write headers if provided
            if headers:
                writer.writerow(headers)
            
            # Write rows
            for i, row in enumerate(rows):
                if isinstance(row, list):
                    writer.writerow(row)
                else:
                    # convert to list if it's not already
                    writer.writerow([row])
        
        total_lines = len(rows) + (1 if headers else 0)

    def run(self, statement: str, dialect: str = "hive", filename: str = "resultats.csv", batch_size: int = 1000):
        """
        Run a SQL statement and save the results to a CSV file.
        Args:
            statement (str): The SQL statement to execute.
            dialect (str): The SQL dialect to use (default is "hive").
            filename (str): The name of the file to save the results to (default is "resultats.csv").
            batch_size (int): Number of rows to fetch per request (default is 1000).
        """ 
        self.login()
        opid = self.execute(statement, dialect)
        self.wait(opid)
        headers, rows = self.fetch_all(opid, batch_size=batch_size)
        self.save_csv(headers, rows, filename)
        
    def list_directory(self, directory_path: str, pagesize: int = 1000) -> List[Dict[str, Any]]:
        """
        List files and directories in the specified path.
        Args:
            directory_path (str): The directory path to list (e.g., "/user/r.lopez/resultsx", "s3a://bucket/path").
            pagesize (int): Maximum number of items to return (default is 1000).
        Returns:
            List[Dict[str, Any]]: List of file/directory information.
        Raises:
            RuntimeError: If the request fails.
        """
        # Encode the path for URL
        from urllib.parse import quote
        encoded_path = quote(directory_path, safe='')
        
        url = f"{self.host}/api/v1/storage/view={encoded_path}"
        params = {"pagesize": pagesize}
        
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        
        data = resp.json()
        files = data.get("files", [])
        
        return files

    def download_file(self, file_path: str, local_filename: Optional[str] = None) -> str:
        """
        Download a file from the remote storage to local filesystem.
        Args:
            file_path (str): The remote file path to download.
            local_filename (str, optional): Local filename to save as. If None, uses the basename of file_path.
        Returns:
            str: The local filename where the file was saved.
        Raises:
            RuntimeError: If the download fails.
        """
        if local_filename is None:
            local_filename = os.path.basename(file_path)
        
        # Encode the path for URL
        encoded_path = quote(file_path, safe='') 
        
        url = f"{self.host}/api/v1/storage/download={encoded_path}"
        
        resp = self.session.get(url, stream=True)
        resp.raise_for_status()
        
        # Ensure local directory exists
        local_dir = os.path.dirname(local_filename)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir)
        
        with open(local_filename, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = os.path.getsize(local_filename)

        return local_filename

    def download_directory_files(self, directory_path: str, local_dir: str = ".", file_pattern: Optional[str] = None) -> List[str]:
        """
        Download all files from a directory (non-recursive).
        Args:
            directory_path (str): The remote directory path.
            local_dir (str): Local directory to save files (default is current directory).
            file_pattern (str, optional): Pattern to filter files (e.g., "part-" to only download part files).
        Returns:
            List[str]: List of local filenames that were downloaded.
        Raises:
            RuntimeError: If any download fails.
        """
        files = self.list_directory(directory_path)
        downloaded_files = []
        
        # Filter only files (not directories) and apply pattern filter if specified
        for file_info in files:
            if file_info.get("type") == "file":
                filename = file_info.get("name", "")
                if file_pattern is None or file_pattern in filename:
                    remote_path = file_info.get("path")
                    if remote_path:
                        local_filename = os.path.join(local_dir, filename)
                        downloaded_file = self.download_file(remote_path, local_filename)
                        downloaded_files.append(downloaded_file)
        
        if not downloaded_files:
            raise RuntimeError(f"No files found matching pattern '{file_pattern}' in directory '{directory_path}'")
        
        return downloaded_files

    def run_and_download(self, statement: str, directory_path: str, local_dir: str = ".", dialect: str = "hive", 
                        file_pattern: Optional[str] = None, poll_interval: int = 2, timeout: int = 300):
        """
        Execute an INSERT OVERWRITE DIRECTORY statement and download the resulting files.
        Args:
            statement (str): The SQL statement to execute (should be INSERT OVERWRITE DIRECTORY).
            directory_path (str): The directory path where files will be created.
            local_dir (str): Local directory to save downloaded files (default is current directory).
            dialect (str): The SQL dialect to use (default is "hive").
            file_pattern (str, optional): Pattern to filter files for download (e.g., "part-").
            poll_interval (int): The interval in seconds to wait between status checks (default is 2).
            timeout (int): The maximum time in seconds to wait for the operation to complete (default is 300).
        Returns:
            List[str]: List of local filenames that were downloaded.
        """
        
        # Authenticate if not already done
        if not self.token:
            self.login()
        
        # Execute the query
        opid = self.execute(statement, dialect)
        
        # Wait for completion
        self.wait(opid, poll_interval=poll_interval, timeout=timeout)
        
        # Download the files
        downloaded_files = self.download_directory_files(directory_path, local_dir, file_pattern)
        
        return downloaded_files

    def check_directory_exists(self, directory_path: str) -> bool:
        """
        Check if a directory exists in the remote storage.
        Args:
            directory_path (str): The directory path to check.
        Returns:
            bool: True if the directory exists, False otherwise.
        """
        try:
            files = self.list_directory(directory_path, pagesize=1)
            return True
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return False
            raise  # Re-raise if it's a different kind of error

    def upload_file(self, dest_path: str, file_path: str):
        """
        Upload a file to the hdfs filesystem
        Args: 
            dest_path (str): The distant directory 
            file_path (str): file path to upload
        Returns : 
            dict: json response
        """
        
        # Fix the URL parameter format
        encoded_path = quote(dest_path, safe='')
        url = f"{self.host}/api/v1/storage/upload/file?dest={encoded_path}"  # Added missing =
        
        filename = os.path.basename(file_path)  # Use filename, not full path
        
        with open(file_path, 'rb') as f:
            # Proper file tuple format: (filename, file_object, content_type)
            files = {'hdfs_file': (filename, f, 'application/octet-stream')}
            data = {'fileFieldName': 'hdfs_file'}  # Often required
            
            response = self.session.post(url, files=files, data=data)
                        
            if response.status_code != 200:
                raise RuntimeError(f"Upload failed: {response.status_code} - {response.text}")
            
            result = response.json()
            if result.get("status") == -1:
                raise RuntimeError(f"Upload failed: {result.get('data')}")
            
            return result