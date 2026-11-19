import os,sys,tempfile
sys.path.insert(0,__import__('pathlib').Path(__file__).resolve().parents[1])
d=tempfile.mkdtemp(prefix='ppdb-')
os.environ['DATABASE_URL']='sqlite:///'+d+'/test.db'
os.environ['REDIS_URL']='redis://127.0.0.1:6399/0'
os.environ['JWT_SECRET']='test-secret'
import fakeredis
_conn=fakeredis.FakeRedis()
import redis
redis.Redis.from_url=classmethod(lambda cls,*a,**k:_conn)
