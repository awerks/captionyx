import os
import queue
import threading
import time


class AsynchronousS3:
    """Download/Upload asynchronously files from/to AWS S3 bucket.
    Example:
    >>> from asynchronous_s3 import AsynchronousS3
    >>>
    >>> def my_success_callback(size, duration):
    ...     print(f'My {size} bytes file has been uploaded in {duration} sec.')
    ...
    >>> def upload_to_s3():
    ...     async_s3 = AsynchronousS3('my-bucket-name')
    ...     async_s3.upload_file(
    ...         'path/to_my/local_file',
    ...         'object/key',
    ...         on_success=my_success_callback,
    ...         on_failure=lambda error: print(error),
    ...     )
    ...     print('code to be executed...')
    ...
    >>> upload_file()
    code to be executed...
    My 105673 bytes file has been uploaded in 5.3242523 sec.
    >>>
    """

    def __init__(self, s3_name, session):
        """Class constructor.
        arguments:
        s3_name -- Name of the bucket. Please check your credentials before
        (~/.aws/credentials)
        args -- extra arguments to give to boto3.session.Session instance.
        Keywords arguments:
        kwargs -- extra kwargs to give to boto3.session.Session instance.
        """
        service_resource = session.resource("s3")
        
        self.bucket = service_resource.Bucket(s3_name)
        self._io_threads_queue = threads_queue = queue.Queue()
        self._daemon = _S3Daemon(threads_queue)

        self._daemon.start()

    def upload_file(self, local_path, key, on_success=None, on_failure=None, context=None, **kwargs):
        """Upload a file from your computer to s3.
        Arguments:
        local_path -- Source path on your computer.
        key -- AWS S3 destination object key. More info:
        https://docs.aws.amazon.com/AmazonS3/latest/dev/UsingMetadata.html
        Keywords arguments:
        on_success -- success callback to call. Given arguments will be:
        file_size and duration. Default is `None`, any callback is called.
        on_failure -- failure callback to call. Given arguments will be:
        error_message. Default is `None`, any callback is called.
        kwargs -- Extra kwargs for standard boto3 Bucket `upload_file` method.
        """
        bucket = self.bucket
        method = bucket.upload_file

        thread = _S3Thread(
            method,
            on_success=on_success,
            on_failure=on_failure,
            threads_queue=self._io_threads_queue,
            Key=key,
            Filename=local_path,
            context=context,
            **kwargs,
        )
        thread.start()

    def dowload_file(self, local_path, key, on_success=None, on_failure=None, context=None, **kwargs):
        """Download a file from S3 to your computer.
        Arguments:
        local_path -- Destination path on your computer.
        key -- AWS S3 source object key. More info:
        https://docs.aws.amazon.com/AmazonS3/latest/dev/UsingMetadata.html
        Keywords arguments:
        on_success -- success callback to call. Given arguments will be:
        file_size and duration. Default is `None`, any callback is called.
        on_failure -- failure callback to call. Given arguments will be:
        error_message. Default is `None`, any callback is called.
        kwargs -- Extra kwargs for standard boto3 Bucket `download_file` method
        """
        bucket = self.bucket
        method = bucket.download_file

        thread = _S3Thread(
            method,
            on_success=on_success,
            on_failure=on_failure,
            threads_queue=self._io_threads_queue,
            Key=key,
            Filename=local_path,
            context=context,
            **kwargs,
        )
        thread.start()

    def exit(self):
        self._daemon.exit()

    def __del__(self):
        self.exit()


class _S3Thread(threading.Thread):
    def __init__(self, method, on_success, on_failure, threads_queue, context, *args, **kwargs):
        self._method = method
        self._on_success = on_success
        self._on_failure = on_failure
        self._context = context
        self._threads_queue = threads_queue
        self._meth_args = args
        self._meth_kwargs = kwargs

        self._start_time = time.time()

        super().__init__()

    def run(self):
        method = self._method
        args = self._meth_args
        kwargs = self._meth_kwargs

        try:
            method(*args, **kwargs)
            self.success()
        except Exception as error:
            self.failed(error)

    def success(self):
        file_path = self._meth_kwargs["Filename"]
        file_size = os.path.getsize(file_path)
        duration = time.time() - self._start_time

        self.stop(self._on_success, file_size, duration, self._context)

    def failed(self, error_message):
        self.stop(self._on_failure, error_message)

    def stop(self, callback, *args):
        if callback is not None:
            callback(*args)

        self._threads_queue.put(self)


class _S3Daemon(threading.Thread):
    def __init__(self, threads_queue):
        self._threads_queue = threads_queue

        self._running_event = threading.Event()
        self._running_event.set()

        super().__init__(daemon=True)

    def run(self):
        while self._running_event.is_set():
            time.sleep(0.1)

            try:
                thread = self._threads_queue.get_nowait()
            except queue.Empty:
                continue

            thread.join(0.2)

    def exit(self):
        self._running_event.clear()
        self.join(0.2)
