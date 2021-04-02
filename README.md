# python-slapd
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
