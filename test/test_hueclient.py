import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import json
import os
from hueclientrest import HueClientREST  # Assuming the class is in paste.py


class TestHueClientREST(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.host = "https://hue.example.com"
        self.username = "testuser"
        self.password = "testpass"
        self.client = HueClientREST(self.host, self.username, self.password)
    
    def test_init_valid_params(self):
        """Test initialization with valid parameters."""
        client = HueClientREST("https://example.com", "user", "pass")
        self.assertEqual(client.host, "https://example.com")
        self.assertEqual(client.username, "user")
        self.assertEqual(client.password, "pass")
        self.assertTrue(client.verify_ssl)
        self.assertIsNone(client.token)
    
    def test_init_empty_host(self):
        """Test initialization with empty host raises ValueError."""
        with self.assertRaises(ValueError):
            HueClientREST("", "user", "pass")
    
    def test_init_none_host(self):
        """Test initialization with None host raises ValueError."""
        with self.assertRaises(ValueError):
            HueClientREST(None, "user", "pass")
    
    @patch('requests.Session.post')
    def test_login_success(self, mock_post):
        """Test successful login."""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access": "test_token_123"}
        mock_post.return_value = mock_response
        
        with patch('builtins.print'):  # Suppress print output
            self.client.login()
        
        self.assertEqual(self.client.token, "test_token_123")
        self.assertEqual(self.client.session.headers["Authorization"], "Bearer test_token_123")
        mock_post.assert_called_once_with(
            f"{self.host}/api/v1/token/auth/",
            data={"username": self.username, "password": self.password}
        )
    
    @patch('requests.Session.post')
    def test_login_failure(self, mock_post):
        """Test login failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_post.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            self.client.login()
        
        self.assertIn("Auth failed: 401", str(context.exception))
    
    @patch('requests.Session.post')
    def test_login_no_token(self, mock_post):
        """Test login with missing token in response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}  # No access token
        mock_post.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            self.client.login()
        
        self.assertIn("No token found", str(context.exception))
    
    @patch('requests.Session.post')
    def test_execute_success(self, mock_post):
        """Test successful query execution."""
        mock_response = Mock()
        mock_response.json.return_value = {"history_uuid": "operation_123"}
        mock_post.return_value = mock_response
        mock_post.return_value.raise_for_status = Mock()
        
        with patch('builtins.print'):
            result = self.client.execute("SELECT * FROM table")
        
        self.assertEqual(result, "operation_123")
        mock_post.assert_called_once_with(
            f"{self.host}/api/v1/editor/execute/hive",
            data={"statement": "SELECT * FROM table"}
        )
    
    @patch('requests.Session.post')
    def test_execute_no_operation_id(self, mock_post):
        """Test execute with missing operation ID."""
        mock_response = Mock()
        mock_response.json.return_value = {}  # No history_uuid or history_id
        mock_post.return_value = mock_response
        mock_post.return_value.raise_for_status = Mock()
        
        with self.assertRaises(RuntimeError) as context:
            self.client.execute("SELECT * FROM table")
        
        self.assertIn("Échec execute", str(context.exception))
    
    @patch('requests.Session.post')
    @patch('time.sleep')
    def test_wait_success(self, mock_sleep, mock_post):
        """Test successful wait for operation completion."""
        # Mock responses: first running, then available
        responses = [
            Mock(json=lambda: {"query_status": {"status": "running"}}),
            Mock(json=lambda: {"query_status": {"status": "available"}})
        ]
        for resp in responses:
            resp.raise_for_status = Mock()
        mock_post.side_effect = responses
        
        with patch('builtins.print'):
            self.client.wait("operation_123", poll_interval=1, timeout=10)
        
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(1)
    
    @patch('requests.Session.post')
    def test_wait_failed_status(self, mock_post):
        """Test wait with failed operation status."""
        mock_response = Mock()
        mock_response.json.return_value = {"query_status": {"status": "failed"}}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        with self.assertRaises(RuntimeError) as context:
            self.client.wait("operation_123")
        
        self.assertIn("Request failed with status : failed", str(context.exception))
    
    @patch('requests.Session.post')
    @patch('time.sleep')
    def test_wait_timeout(self, mock_sleep, mock_post):
        """Test wait timeout."""
        mock_response = Mock()
        mock_response.json.return_value = {"query_status": {"status": "running"}}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        with self.assertRaises(TimeoutError):
            with patch('builtins.print'):
                self.client.wait("operation_123", poll_interval=1, timeout=2)
    
    @patch('requests.Session.post')
    def test_fetch_all_success(self, mock_post):
        """Test successful fetch of all results."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "status": 0,
            "result": {
                "meta": [{"name": "col1"}, {"name": "col2"}],
                "data": [["row1_col1", "row1_col2"], ["row2_col1", "row2_col2"]],
                "has_more": False
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        with patch('builtins.print'):
            headers, rows = self.client.fetch_all("operation_123")
        
        self.assertEqual(headers, ["col1", "col2"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["row1_col1", "row1_col2"])
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('csv.writer')
    def test_save_csv(self, mock_writer, mock_file):
        """Test saving results to CSV."""
        mock_csv_writer = Mock()
        mock_writer.return_value = mock_csv_writer
        
        headers = ["col1", "col2"]
        rows = [["val1", "val2"], ["val3", "val4"]]
        
        with patch('builtins.print'):
            self.client.save_csv(headers, rows, "test.csv")
        
        mock_file.assert_called_once_with("test.csv", "w", newline="", encoding="utf-8")
        mock_csv_writer.writerow.assert_any_call(headers)
        mock_csv_writer.writerow.assert_any_call(["val1", "val2"])
        mock_csv_writer.writerow.assert_any_call(["val3", "val4"])
    
    @patch.object(HueClientREST, 'save_csv')
    @patch.object(HueClientREST, 'fetch_all')
    @patch.object(HueClientREST, 'wait')
    @patch.object(HueClientREST, 'execute')
    @patch.object(HueClientREST, 'login')
    def test_run_complete_workflow(self, mock_login, mock_execute, mock_wait, mock_fetch, mock_save):
        """Test complete run workflow."""
        mock_execute.return_value = "operation_123"
        mock_fetch.return_value = (["col1"], [["val1"]])
        
        self.client.run("SELECT * FROM table", filename="output.csv")
        
        mock_login.assert_called_once()
        mock_execute.assert_called_once_with("SELECT * FROM table", "hive")
        mock_wait.assert_called_once_with("operation_123")
        mock_fetch.assert_called_once_with("operation_123", batch_size=1000)
        mock_save.assert_called_once_with(["col1"], [["val1"]], "output.csv")
    
    @patch('requests.Session.get')
    def test_list_directory_success(self, mock_get):
        """Test successful directory listing."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "files": [
                {"name": "file1.txt", "type": "file"},
                {"name": "subdir", "type": "directory"}
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        with patch('builtins.print'):
            files = self.client.list_directory("/user/test")
        
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["name"], "file1.txt")
    
    @patch('requests.Session.get')
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.getsize')
    @patch('os.makedirs')
    @patch('os.path.exists')
    @patch('os.path.dirname')
    def test_download_file_success(self, mock_dirname, mock_exists, mock_makedirs, 
                                  mock_getsize, mock_file, mock_get):
        """Test successful file download."""
        mock_dirname.return_value = ""
        mock_exists.return_value = True
        mock_getsize.return_value = 1024
        
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"file_content"]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        with patch('builtins.print'):
            result = self.client.download_file("/remote/file.txt", "local_file.txt")
        
        self.assertEqual(result, "local_file.txt")
        mock_file.assert_called_once_with("local_file.txt", 'wb')
    
    @patch.object(HueClientREST, 'list_directory')
    def test_check_directory_exists_true(self, mock_list):
        """Test directory exists check returns True."""
        mock_list.return_value = []
        
        result = self.client.check_directory_exists("/existing/path")
        
        self.assertTrue(result)
        mock_list.assert_called_once_with("/existing/path", pagesize=1)
    
    @patch.object(HueClientREST, 'list_directory')
    def test_check_directory_exists_false(self, mock_list):
        """Test directory exists check returns False for 404."""
        mock_list.side_effect = Exception("404 not found")
        
        result = self.client.check_directory_exists("/nonexistent/path")
        
        self.assertFalse(result)

    @patch('builtins.open', new_callable=mock_open, read_data=b'test file content')
    @patch('os.path.basename')
    @patch('requests.Session.post')
    @patch('builtins.print')  # Mock print to avoid cluttering test output
    def test_upload_file_success(self, mock_print, mock_post, mock_basename, mock_file):
        """Test successful file upload."""
        # Setup mocks
        mock_basename.return_value = "test.txt"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": 0, "message": "Upload successful"}
        mock_post.return_value = mock_response
        
        # Execute
        result = self.client.upload_file("/user/testuser/data/", "/local/test.txt")
        
        # Verify
        self.assertEqual(result, {"status": 0, "message": "Upload successful"})
        
        # Verify URL construction (expect URL-encoded slashes)
        expected_url = f"{self.host}/api/v1/storage/upload/file?dest=%2Fuser%2Ftestuser%2Fdata%2F"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], expected_url)
        
        # Verify files parameter
        files_param = call_args[1]['files']
        self.assertIn('hdfs_file', files_param)
        filename, file_obj, content_type = files_param['hdfs_file']
        self.assertEqual(filename, "test.txt")
        self.assertEqual(content_type, 'application/octet-stream')
        
        # Verify data parameter
        data_param = call_args[1]['data']
        self.assertEqual(data_param, {'fileFieldName': 'hdfs_file'})
        
        # Verify file operations
        mock_file.assert_called_once_with("/local/test.txt", 'rb')
        mock_basename.assert_called_once_with("/local/test.txt")

    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.basename')
    @patch('urllib.parse.quote')
    @patch('requests.Session.post')
    @patch('builtins.print')
    def test_upload_file_http_error(self, mock_print, mock_post, mock_quote, mock_basename, mock_file):
        """Test upload with HTTP error response."""
        # Setup mocks
        mock_basename.return_value = "test.txt"
        mock_quote.return_value = "encoded_path"
        
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response
        
        # Execute and verify exception
        with self.assertRaises(RuntimeError) as context:
            self.client.upload_file("/dest/path/", "/local/test.txt")
        
        self.assertIn("Upload failed: 500 - Internal Server Error", str(context.exception))
        
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.basename')
    @patch('urllib.parse.quote')
    @patch('requests.Session.post')
    @patch('builtins.print')
    def test_upload_file_api_error(self, mock_print, mock_post, mock_quote, mock_basename, mock_file):
        """Test upload with API-level error (status: -1)."""
        # Setup mocks
        mock_basename.return_value = "test.txt"
        mock_quote.return_value = "encoded_path"
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": -1, "data": "Permission denied"}
        mock_post.return_value = mock_response
        
        # Execute and verify exception
        with self.assertRaises(RuntimeError) as context:
            self.client.upload_file("/dest/path/", "/local/test.txt")
        
        self.assertIn("Upload failed: Permission denied", str(context.exception))

if __name__ == '__main__':
    # Run with: python -m pytest test_hue_client.py -v
    # Or: python test_hue_client.py
    unittest.main()