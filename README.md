# python-slapd [![Documentation Status](https://readthedocs.org/projects/slapd/badge/?version=latest)](https://slapd.readthedocs.io/en/latest/?badge=latest)
Controls your OpenLDAP process in a pythonic way.

```
pip install slapd
```

```python
>>> import slapd
>>> process = slapd.Slapd()
>>> process.start()
>>> process.init_tree()
>>> process.ldapwhoami().stdout.decode("utf-8")
'dn:cn=manager,dc=slapd-test,dc=python-ldap,dc=org\n'
>>> process.stop()
```

# Troubleshooting

On distributions like Ubuntu, apparmor may restrict *slapd* to access some files that
*python-slapd* has generated. This situation can be solved by passing slapd in complain mode:

```bash
sudo apt install --yes apparmor-utils
sudo aa-complain /usr/sbin/slapd
```
