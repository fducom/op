# -*- coding: utf-8 -*-
from barbecue import chef
from logging import getLogger
from openprocurement.api.constants import TZ
from pkg_resources import get_distribution
from openprocurement.api.utils import get_now, context_unpack
from openprocurement.tender.core.utils import cleanup_bids_for_cancelled_lots, remove_draft_bids

PKG = get_distribution(__package__)
LOGGER = getLogger(PKG.project_name)


def check_bids(request):
    tender = request.validated['tender']
    if tender.lots:
        [setattr(i.auctionPeriod, 'startDate', None) for i in tender.lots if i.numberOfBids < 2 and i.auctionPeriod and i.auctionPeriod.startDate]
        [setattr(i, 'status', 'unsuccessful') for i in tender.lots if i.numberOfBids == 0 and i.status == 'active']
        cleanup_bids_for_cancelled_lots(tender)
        if not set([i.status for i in tender.lots]).difference(set(['unsuccessful', 'cancelled'])):
            tender.status = 'unsuccessful'
        elif max([i.numberOfBids for i in tender.lots if i.status == 'active']) < 2:
            add_next_award(request)
    else:
        if tender.numberOfBids < 2 and tender.auctionPeriod and tender.auctionPeriod.startDate:
            tender.auctionPeriod.startDate = None
        if tender.numberOfBids == 0:
            tender.status = 'unsuccessful'
        if tender.numberOfBids == 1:
            add_next_award(request)


def check_status(request):
    tender = request.validated['tender']
    now = get_now()
    for award in tender.awards:
        if award.status == 'active' and not any([i.awardID == award.id for i in tender.contracts]):
            tender.contracts.append(type(tender).contracts.model_class({
                'awardID': award.id,
                'suppliers': award.suppliers,
                'value': award.value,
                'date': now,
                'items': [i for i in tender.items if i.relatedLot == award.lotID],
                'contractID': '{}-{}{}'.format(tender.tenderID, request.registry.server_id, len(tender.contracts) + 1)}))
            add_next_award(request)
    if tender.status == 'active.enquiries' and not tender.tenderPeriod.startDate and tender.enquiryPeriod.endDate.astimezone(TZ) <= now:
        LOGGER.info('Switched tender {} to {}'.format(tender.id, 'active.tendering'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_active.tendering'}))
        tender.status = 'active.tendering'
        return
    elif tender.status == 'active.enquiries' and tender.tenderPeriod.startDate and tender.tenderPeriod.startDate.astimezone(TZ) <= now:
        LOGGER.info('Switched tender {} to {}'.format(tender.id, 'active.tendering'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_active.tendering'}))
        tender.status = 'active.tendering'
        return
    elif not tender.lots and tender.status == 'active.tendering' and tender.tenderPeriod.endDate <= now:
        LOGGER.info('Switched tender {} to {}'.format(tender['id'], 'active.auction'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_active.auction'}))
        tender.status = 'active.auction'
        remove_draft_bids(request)
        check_bids(request)
        if tender.numberOfBids < 2 and tender.auctionPeriod:
            tender.auctionPeriod.startDate = None
        return
    elif tender.lots and tender.status == 'active.tendering' and tender.tenderPeriod.endDate <= now:
        LOGGER.info('Switched tender {} to {}'.format(tender['id'], 'active.auction'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_active.auction'}))
        tender.status = 'active.auction'
        remove_draft_bids(request)
        check_bids(request)
        [setattr(i.auctionPeriod, 'startDate', None) for i in tender.lots if i.numberOfBids < 2 and i.auctionPeriod]
        return


def check_tender_status(request):
    tender = request.validated['tender']
    now = get_now()
    if tender.lots:
        for lot in tender.lots:
            if lot.status != 'active':
                continue
            lot_awards = [i for i in tender.awards if i.lotID == lot.id]
            if not lot_awards:
                continue
            last_award = lot_awards[-1]
            if last_award.status == 'unsuccessful':
                LOGGER.info('Switched lot {} of tender {} to {}'.format(lot.id, tender.id, 'unsuccessful'),
                            extra=context_unpack(request, {'MESSAGE_ID': 'switched_lot_unsuccessful'}, {'LOT_ID': lot.id}))
                lot.status = 'unsuccessful'
                continue
            elif last_award.status == 'active' and any([i.status == 'active' and i.awardID == last_award.id for i in tender.contracts]):
                LOGGER.info('Switched lot {} of tender {} to {}'.format(lot.id, tender.id, 'complete'),
                            extra=context_unpack(request, {'MESSAGE_ID': 'switched_lot_complete'}, {'LOT_ID': lot.id}))
                lot.status = 'complete'
        statuses = set([lot.status for lot in tender.lots])

        if statuses == set(['cancelled']):
            LOGGER.info('Switched tender {} to {}'.format(tender.id, 'cancelled'),
                        extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_cancelled'}))
            tender.status = 'cancelled'
        elif not statuses.difference(set(['unsuccessful', 'cancelled'])):
            LOGGER.info('Switched tender {} to {}'.format(tender.id, 'unsuccessful'),
                        extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_unsuccessful'}))
            tender.status = 'unsuccessful'
        elif not statuses.difference(set(['complete', 'unsuccessful', 'cancelled'])):
            LOGGER.info('Switched tender {} to {}'.format(tender.id, 'complete'),
                        extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_complete'}))
            tender.status = 'complete'
    else:
        last_award_status = tender.awards[-1].status if tender.awards else ''
        if last_award_status == 'unsuccessful':
            LOGGER.info('Switched tender {} to {}'.format(tender.id, 'unsuccessful'),
                        extra=context_unpack(request, {'MESSAGE_ID': 'switched_tender_unsuccessful'}))
            tender.status = 'unsuccessful'
        if tender.contracts and tender.contracts[-1].status == 'active':
            tender.status = 'complete'


def add_next_award(request):
    tender = request.validated['tender']
    now = get_now()
    if not tender.awardPeriod:
        tender.awardPeriod = type(tender).awardPeriod({})
    if not tender.awardPeriod.startDate:
        tender.awardPeriod.startDate = now
    if tender.lots:
        statuses = set()
        for lot in tender.lots:
            if lot.status != 'active':
                continue
            lot_awards = [i for i in tender.awards if i.lotID == lot.id]
            if lot_awards and lot_awards[-1].status in ['pending', 'active']:
                statuses.add(lot_awards[-1].status if lot_awards else 'unsuccessful')
                continue
            lot_items = [i.id for i in tender.items if i.relatedLot == lot.id]
            features = [
                i
                for i in (tender.features or [])
                if i.featureOf == 'tenderer' or i.featureOf == 'lot' and i.relatedItem == lot.id or i.featureOf == 'item' and i.relatedItem in lot_items
            ]
            codes = [i.code for i in features]
            bids = [
                {
                    'id': bid.id,
                    'value': [i for i in bid.lotValues if lot.id == i.relatedLot][0].value,
                    'tenderers': bid.tenderers,
                    'parameters': [i for i in bid.parameters if i.code in codes],
                    'date': [i for i in bid.lotValues if lot.id == i.relatedLot][0].date
                }
                for bid in tender.bids
                if lot.id in [i.relatedLot for i in bid.lotValues]
            ]
            if not bids:
                lot.status = 'unsuccessful'
                statuses.add('unsuccessful')
                continue
            unsuccessful_awards = [i.bid_id for i in lot_awards if i.status == 'unsuccessful']
            bids = chef(bids, features, unsuccessful_awards)
            if bids:
                bid = bids[0]
                award = type(tender).awards.model_class({
                    'bid_id': bid['id'],
                    'lotID': lot.id,
                    'status': 'pending',
                    'value': bid['value'],
                    'date': get_now(),
                    'suppliers': bid['tenderers'],
                })
                tender.awards.append(award)
                request.response.headers['Location'] = request.route_url('{}:Tender Awards'.format(tender.procurementMethodType), tender_id=tender.id, award_id=award['id'])
                statuses.add('pending')
            else:
                statuses.add('unsuccessful')
        if statuses.difference(set(['unsuccessful', 'active'])):
            tender.awardPeriod.endDate = None
            tender.status = 'active.qualification'
        else:
            tender.awardPeriod.endDate = now
            tender.status = 'active.awarded'
    else:
        if not tender.awards or tender.awards[-1].status not in ['pending', 'active']:
            unsuccessful_awards = [i.bid_id for i in tender.awards if i.status == 'unsuccessful']
            bids = chef(tender.bids, tender.features or [], unsuccessful_awards)
            if bids:
                bid = bids[0].serialize()
                award = type(tender).awards.model_class({
                    'bid_id': bid['id'],
                    'status': 'pending',
                    'date': get_now(),
                    'value': bid['value'],
                    'suppliers': bid['tenderers']
                })
                tender.awards.append(award)
                request.response.headers['Location'] = request.route_url('{}:Tender Awards'.format(tender.procurementMethodType), tender_id=tender.id, award_id=award['id'])
        if tender.awards[-1].status == 'pending':
            tender.awardPeriod.endDate = None
            tender.status = 'active.qualification'
        else:
            tender.awardPeriod.endDate = now
            tender.status = 'active.awarded'


def prepare_shortlistedFirms(shortlistedFirms):
    """ Make list with keys
        key = {identifier_id}_{identifier_scheme}_{lot_id}
    """
    shortlistedFirms = shortlistedFirms if shortlistedFirms else []
    all_keys = set()
    for firm in shortlistedFirms:
        key = u"{firm_id}_{firm_scheme}".format(firm_id=firm['identifier']['id'],
                                                firm_scheme=firm['identifier']['scheme'])
        #if firm.get('lots'):
            #keys = set([u"{key}_{lot_id}".format(key=key, lot_id=lot['id']) for lot in firm.get('lots')])
        #else:
            #keys = set([key])
        keys = set([key])
        all_keys |= keys
    return all_keys


def prepare_bid_identifier(bid):
    """ Make list with keys
        key = {identifier_id}_{identifier_scheme}_{lot_id}
    """
    all_keys = set()
    for tenderer in bid['tenderers']:
        key = u"{id}_{scheme}".format(id=tenderer['identifier']['id'],
                                      scheme=tenderer['identifier']['scheme'])
        #if bid.get('lotValues'):
            #keys = set([u"{key}_{lot_id}".format(key=key,
                                                 #lot_id=lot['relatedLot'])
                        #for lot in bid.get('lotValues')])
        #else:
            #keys = set([key])
        keys = set([key])
        all_keys |= keys
    return all_keys
