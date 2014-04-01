#!/usr/bin/env python
from os import mkdir
from pickle import load, dump
from execo import logger
from execo_g5k import get_resource_attributes, get_g5k_sites, get_site_clusters
from networkx import Graph, set_edge_attributes, get_edge_attributes

_default_cache_dir = 'cache/'
_arbitrary_latency = 2.25E-3


def get_topology(cache_dir=_default_cache_dir, resources=['grid5000']):
    """Create three dicts containing the data from backbone, equips and hosts
    """
    logger.info('Retrieving topology data')
    if _check_topology_cache(cache_dir):
        backbone, equips, hosts = _get_topology_cache(cache_dir, resources)
    else:
        backbone, equips, hosts = _read_topology_cache(cache_dir, resources)

    return backbone, equips, hosts


def get_backbone_graph(backbone, latency=_arbitrary_latency):
    if backbone is None:
        backbone, _, _ = get_topology()
    gr = Graph()
    # Adding backbone equipments and links
    for equip in backbone:
        src = equip['uid']
        if not gr.has_node(src):
            gr.add_node(src, kind='renater')
        for lc in equip['linecards']:
            for port in lc['ports']:
                kind = 'renater' if not 'kind' in port else port['kind']
                dst = port['uid'] if not 'site_uid' in port else port['uid'] \
                + '.' + port['site_uid']
                rate = lc['rate'] if not 'rate' in port else port['rate']
                if not gr.has_node(dst):
                    gr.add_node(dst, kind=kind)
                if not gr.has_edge(src, dst):
                    gr.add_edge(src, dst, bandwidth=rate, latency=latency)
    return gr


def get_site_graph(site, hosts, equips, latency=_arbitrary_latency):
    sgr = Graph()
    for equip in equips:
        src = equip['uid'] + '.' + site
        if not sgr.has_node(src):
            sgr.add_node(src, kind=equip['kind'])
        for lc in filter(lambda n: 'ports' in n, equip['linecards']):
            if not 'kind' in lc:
                lc['kind'] = 'unknown'
            for port in filter(lambda p: 'uid' in p, lc['ports']):
                kind = lc['kind'] if not 'kind' in port else port['kind']
                dst = port['uid'] + '.' + site
                rate = lc['rate'] if not 'rate' in port else port['rate']
                if kind in ['switch', 'router']:
                    if not sgr.has_node(dst):
                        sgr.add_node(dst, kind=kind)
                    if not sgr.has_edge(src, dst):
                        sgr.add_edge(src, dst, bandwidth=rate, latency=latency)
                    else:
                        tmp = get_edge_attributes(sgr, 'bandwidth')
                        if (src, dst) in tmp.keys():
                            set_edge_attributes(sgr, 'bandwidth',
                                        {(src, dst): rate + tmp[(src, dst)]})

    for cluster_hosts in hosts.itervalues():
        for host in cluster_hosts:
            src = host['uid'] + '.' + site
            if not sgr.has_node(src):
                sgr.add_node(src, kind='node',
                             power=host['performance']['core_flops'],
                             core=host['architecture']['smt_size'])
            for adapt in filter(lambda n: n['enabled'] and not n['management']
                                and n['interface'] == 'Ethernet',
                                host['network_adapters']):
                if adapt['switch'] is None:
                    print site, src, dst
                else:
                    dst = adapt['switch'] + '.' + site
                if not sgr.has_edge(src, dst):
                    sgr.add_edge(src, dst, bandwidth=adapt['rate'],
                                 latency=latency, weight=0.5)
    return sgr


def _get_api_commit():
    """Retrieve the latest api commit """
    return get_resource_attributes('')['version']


def _get_topology_cache(cache_dir=_default_cache_dir, resources=['grid5000']):
    """Retrieve data from the API and write it into the cache directory"""
    try:
        mkdir(cache_dir)
        logger.debug('No cache found, directory created.')
    except:
        logger.debug('Cache directory is present')
        pass
    equips, hosts = {}, {}
    logger.info('Retrieving topology data from API...')
    n_requests = 2
    backbone = get_resource_attributes('/network_equipments')['items']
    f = open(cache_dir + 'backbone', 'w')
    dump(backbone, f)
    f.close()

    for site in sorted(get_g5k_sites()):
        logger.info(site)
        n_requests += 1
        hosts[site] = {}
        for cluster in get_site_clusters(site):
            logger.info('* ' + cluster)
            n_requests += 1
            hosts[site][cluster] = get_resource_attributes(
                'sites/' + site + '/clusters/' + cluster + '/nodes')['items']
            f = open(cache_dir + cluster + '_hosts', 'w')
            dump(hosts[site][cluster], f)
            f.close()

        n_requests += 1
        f = open(cache_dir + site + '_equips', 'w')
        equips[site] = get_resource_attributes(
                    'sites/' + site + '/network_equipments')['items']
        dump(equips[site], f)
        f.close()

    f = open(cache_dir + 'api_commit', 'w')
    f.write(_get_api_commit())
    f.close()
    logger.debug('n_requests = ' + str(n_requests))

    return backbone, equips, hosts


def _read_topology_cache(cache_dir=_default_cache_dir, resources=['grid5000']):
    """Read the json files from cache_dir and return three dicts
    - backbone = the backbone data
    - ne = the network_equipements of all sites
    - hosts = the hosts of all sites"""
    equips, hosts = {}, {}

    f_backbone = open('cache/backbone')
    backbone = load(f_backbone)
    f_backbone.close()

    for site in get_g5k_sites():
        logger.debug('Reading equips')
        f_equips = open('cache/' + site + '_equips')
        equips[site] = load(f_equips)
        f_equips.close()
        hosts[site] = {}
        for cluster in get_site_clusters(site):
            f_hosts = open('cache/' + cluster + '_hosts')
            hosts[site][cluster] = load(f_hosts)
            f_hosts.close()

    return backbone, equips, hosts


def _check_topology_cache(cache_dir=_default_cache_dir):
    """Try to read the api_commit stored in the cache_dir and compare
    it with latest commit, return True if remote commit is different
    from cache commit"""
    cache_is_old = False
    try:
        f = open(cache_dir + '/api_commit')
        local_commit = f.readline()
        f.close()
        if local_commit != _get_api_commit():
            logger.debug('Cache is too old')
            cache_is_old = True
        else:
            logger.debug('Already at the latest commit')
    except:
        pass
        logger.debug('No commit version found')
        cache_is_old = True

    return cache_is_old
