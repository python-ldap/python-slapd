# python-slapd [![Documentation Status](https://readthedocs.org/projects/slapd/badge/?version=latest)](https://slapd.readthedocs.io/en/latest/?badge=latest)
Controls your OpenLDAP process in a pythonic way.

```
pip install slapd
```

```python
>>> import slapd
>>> process = slapd.Slapd()
>>> process.start()
>>> process.ldapwhoami().stdout.decode("utf-8")
'dn:cn=manager,dc=slapd-test,dc=python-ldap,dc=org\n'
>>> process.stop()
```
