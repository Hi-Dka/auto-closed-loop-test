import uvicorn
from multiprocessing import Process

from app.odr_executor.odr_executor import odr_executor_app
from app.scheduler.scheduler import scheduler_app


def run_odr():
    uvicorn.run(odr_executor_app, host="localhost", port=8080, log_level="info")


def run_scheduler():
    uvicorn.run(scheduler_app, host="localhost", port=8090, log_level="info")


if __name__ == "__main__":
    p1 = Process(target=run_odr)
    p2 = Process(target=run_scheduler)

    # p1.start()
    p2.start()

    # p1.join()
    p2.join()
