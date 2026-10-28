import sys
import multiprocessing
import pytest
from photoprep.main import main


@pytest.mark.parametrize('arguments',[
    ['PhotoPrep','-B','-S','-I','-c','from multiprocessing.resource_tracker import main;main(3)'],
    ['PhotoPrep','--multiprocessing-fork','tracker_fd=3','pipe_handle=4'],
    ['PhotoPrep','--photoprep-worker','inpaint','request.json'],
    ['PhotoPrep'],
])
def test_freeze_support_precedes_gui_and_worker_dispatch(monkeypatch,arguments):
    monkeypatch.setattr(sys,'argv',arguments)
    class HelperDispatched(Exception):pass
    def dispatch():raise HelperDispatched
    monkeypatch.setattr(multiprocessing,'freeze_support',dispatch)
    with pytest.raises(HelperDispatched):main()
