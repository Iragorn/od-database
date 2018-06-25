from crawl_server import logger
import config
from crawl_server.database import TaskManagerDatabase, Task, TaskResult
from multiprocessing import Manager, Pool
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from crawl_server.crawler import RemoteDirectoryCrawler


class TaskManager:

    def __init__(self, db_path, max_processes=2):
        self.db_path = db_path
        self.db = TaskManagerDatabase(db_path)
        self.pool = Pool(maxtasksperchild=1, processes=max_processes)
        self.max_processes = max_processes
        manager = Manager()
        self.current_tasks = manager.list()

        scheduler = BackgroundScheduler()
        scheduler.add_job(self.execute_queued_task, "interval", seconds=1)
        scheduler.start()

    def put_task(self, task: Task):
        self.db.put_task(task)

    def get_tasks(self):
        return self.db.get_tasks()

    def pop_tasks(self):
        return self.db.pop_all_tasks()

    def get_current_tasks(self):
        return self.current_tasks

    def get_non_indexed_results(self):
        return self.db.get_non_indexed_results()

    def execute_queued_task(self):

        if len(self.current_tasks) <= self.max_processes:
            task = self.db.pop_task()
            if task:
                logger.info("Submitted " + task.url + " to process pool")
                self.current_tasks.append(task)

                self.pool.apply_async(
                    TaskManager.run_task,
                    args=(task, self.db_path, self.current_tasks),
                    callback=TaskManager.task_complete,
                    error_callback=TaskManager.task_error
                )

    @staticmethod
    def run_task(task, db_path, current_tasks):

        result = TaskResult()
        result.start_time = datetime.utcnow()
        result.website_id = task.website_id

        logger.info("Starting task " + task.url)

        crawler = RemoteDirectoryCrawler(task.url, config.CRAWL_SERVER_THREADS)
        crawl_result = crawler.crawl_directory("./crawled/" + str(task.website_id) + ".json")
        del crawler

        result.file_count = crawl_result.file_count
        result.status_code = crawl_result.status_code

        result.end_time = datetime.utcnow()
        logger.info("End task " + task.url)

        # TODO: Figure out the callbacks
        # callback = PostCrawlCallbackFactory.get_callback(task)
        # if callback:
        #     callback.run()

        return result, db_path, current_tasks

    @staticmethod
    def task_error(result):
        logger.error("Uncaught exception during a task: ")
        raise result

    @staticmethod
    def task_complete(result):

        task_result, db_path, current_tasks = result

        logger.info("Task completed, logger result to database")
        logger.info("Status code: " + task_result.status_code)
        logger.info("File count: " + str(task_result.file_count))

        db = TaskManagerDatabase(db_path)
        db.log_result(task_result)

        for i, task in enumerate(current_tasks):
            if task.website_id == task_result.website_id:
                del current_tasks[i]


