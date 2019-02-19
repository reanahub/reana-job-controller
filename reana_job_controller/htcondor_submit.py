#! /bin/env python

# Simple test to submit to the host schedd
# via htcondor python bindings.

import os
import sys
import htcondor
import classad
from retrying import retry

def detach(f):
    """Decorator for creating a forked process"""

    def fork(*args, **kwargs):
        pid = os.fork()
        if pid == 0:
            try:
                os.setuid(int(os.environ.get('VC3USERID')))
                f(*args, **kwargs)
            finally:
                os._exit(0)

    return fork

@retry(stop_max_attempt_number=5)
@detach
def submit(schedd, sub):
    try:
        with schedd.transaction() as txn:
            print(sub.queue(txn))
    except Exception as e:
        print("Error submission: {0}".format(e))
        raise(Exception)

# Address not needed if '--network host' is set
scheddAd = classad.ClassAd()
scheddAd["MyAddress"] = os.environ.get("HTCONDOR_ADDR", None) 
schedd = htcondor.Schedd(scheddAd)
sub = htcondor.Submit({"executable": "/bin/sleep", "arguments": "5m"})
submit(schedd, sub)

