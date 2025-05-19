# examples/13_order_lifecycle_tracker_with_stream.py
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

import logging
import time
import pprint
import argparse
from typing import Any, Optional, Dict

from tsxapipy import (
    APIClient,
    UserHubStream,
    OrderPlacer,
    authenticate,
    AuthenticationError,
    ConfigurationError,
    APIError,
    DEFAULT_CONFIG_CONTRACT_ID,
    DEFAULT_CONFIG_ACCOUNT_ID_TO_WATCH,
    ORDER_STATUS_TO_STRING_MAP, # For logging status
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_WORKING
)

# --- Configure Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s [%(levelname)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("OrderLifecycleTrackerExample")

# --- State for the tracked order ---
tracked_order_id: Optional[int] = None
tracked_order_status_from_stream: Optional[int] = None
tracked_order_details_from_stream: Optional[Dict[str, Any]] = None
is_order_terminal: bool = False # Flag to stop main loop once order is filled/cancelled/rejected

def handle_tracked_order_update(order_data: Any):
    global tracked_order_id, tracked_order_status_from_stream, tracked_order_details_from_stream, is_order_terminal
    
    order_id_from_event = order_data.get("id")
    
    if order_id_from_event == tracked_order_id:
        logger.info(f"--- TRACKED ORDER UPDATE (ID: {tracked_order_id}) ---")
        
        status_code = order_data.get("status")
        status_str = ORDER_STATUS_TO_STRING_MAP.get(status_code, f"UNKNOWN_STATUS({status_code})")
        
        logger.info(f"  New Status: {status_str} (Code: {status_code})")
        logger.info(f"  CumQty: {order_data.get('cumQuantity')}, LeavesQty: {order_data.get('leavesQuantity')}")
        logger.info(f"  AvgPx: {order_data.get('avgPx')}")
        logger.debug(f"  Full data: {pprint.pformat(order_data)}")

        tracked_order_status_from_stream = status_code
        tracked_order_details_from_stream = order_data

        if status_code in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELLED, ORDER_STATUS_REJECTED]:
            logger.info(f"Tracked order {tracked_order_id} reached terminal state: {status_str}. Stopping monitoring for this order.")
            is_order_terminal = True
    else:
        # Log other order updates if needed, but don't act on them for this example's focus
        logger.debug(f"Received update for non-tracked order ID: {order_id_from_event}")


def handle_user_stream_state(state: str):
    logger.info(f"UserHubStream state changed to: {state}")

def handle_user_stream_error(error: Any):
    logger.error(f"UserHubStream error: {error}")


def run_order_lifecycle_example(contract_id: str, account_id: int, limit_price_offset: float = -10.0):
    global tracked_order_id, is_order_terminal
    
    logger.info(f"--- Example: Order Lifecycle Tracker via UserHubStream ---")
    logger.info(f"Contract: {contract_id}, Account: {account_id}, Price Offset for Limit: {limit_price_offset}")

    api_client: Optional[APIClient] = None
    order_placer: Optional[OrderPlacer] = None
    user_stream: Optional[UserHubStream] = None

    # Determine a far-out limit price
    # This is a very naive way to get a price; in a real app, you'd get current market price.
    # For NQ, an offset of -10.0 from an arbitrary high number should be safe.
    # For other contracts, this price might be too high or too low.
    base_price_for_limit = 18000.0 # Placeholder for NQ-like contract
    if "CL" in contract_id.upper(): base_price_for_limit = 70.0
    elif "GC" in contract_id.upper(): base_price_for_limit = 2000.0
    
    target_limit_price = base_price_for_limit + limit_price_offset
    logger.info(f"Calculated target limit price for BUY order: {target_limit_price}")


    try:
        logger.info("Authenticating...")
        initial_token, token_acquired_at = authenticate()
        
        api_client = APIClient(initial_token=initial_token, token_acquired_at=token_acquired_at)
        logger.info("APIClient initialized.")

        order_placer = OrderPlacer(api_client, account_id, default_contract_id=contract_id)
        logger.info("OrderPlacer initialized.")

        # Setup UserHubStream
        logger.info(f"Initializing UserHubStream for account: {account_id}")
        user_stream = UserHubStream(
            api_client=api_client,
            account_id_to_watch=account_id,
            on_order_update=handle_tracked_order_update,
            subscribe_to_accounts_globally=False, # We only care about orders for this account
            on_state_change_callback=handle_user_stream_state,
            on_error_callback=handle_user_stream_error
        )
        if not user_stream.start():
            logger.error("Failed to start UserHubStream. Exiting.")
            return
        logger.info("UserHubStream started.")
        time.sleep(2) # Give stream a moment to fully connect and send initial subscriptions

        # Place the test order
        logger.info(f"Placing LIMIT BUY order: 1 lot of {contract_id} at {target_limit_price} on account {account_id}...")
        placed_order_id = order_placer.place_limit_order(
            side="BUY", 
            size=1, 
            limit_price=target_limit_price,
            contract_id=contract_id
        )

        if not placed_order_id:
            logger.error("Failed to place the initial test order. Exiting example.")
            if user_stream: user_stream.stop()
            return
        
        tracked_order_id = placed_order_id
        logger.info(f"Test order placed successfully! Order ID to track: {tracked_order_id}. Monitoring stream for updates...")

        # Monitor for a while, then attempt to cancel
        monitoring_duration_before_cancel = 20 # seconds
        cancel_attempt_timeout = 15 # seconds to wait for cancel confirmation
        
        start_monitor_time = time.monotonic()
        while time.monotonic() - start_monitor_time < monitoring_duration_before_cancel:
            if is_order_terminal:
                logger.info(f"Order {tracked_order_id} became terminal before cancel attempt. Loop ending.")
                break
            logger.debug(f"Monitoring order {tracked_order_id}... Current status from stream: "
                         f"{ORDER_STATUS_TO_STRING_MAP.get(tracked_order_status_from_stream, 'Not Yet Seen')}")
            time.sleep(1)
        
        if not is_order_terminal:
            logger.info(f"\nAttempting to cancel order {tracked_order_id}...")
            cancel_success = order_placer.cancel_order(order_id=tracked_order_id)
            if cancel_success:
                logger.info(f"Cancel request for order {tracked_order_id} submitted. Waiting for stream confirmation...")
                
                cancel_confirm_start_time = time.monotonic()
                while time.monotonic() - cancel_confirm_start_time < cancel_attempt_timeout:
                    if is_order_terminal and tracked_order_status_from_stream == ORDER_STATUS_CANCELLED:
                        logger.info(f"Order {tracked_order_id} successfully confirmed as CANCELLED via stream.")
                        break
                    elif is_order_terminal: # Filled or Rejected instead of Cancelled
                        logger.warning(f"Order {tracked_order_id} became terminal with status "
                                       f"{ORDER_STATUS_TO_STRING_MAP.get(tracked_order_status_from_stream)} "
                                       f"during/after cancel attempt.")
                        break
                    time.sleep(0.5)
                else: # Timeout waiting for cancel confirmation
                    logger.warning(f"Timed out waiting for cancellation confirmation for order {tracked_order_id} via stream. "
                                   f"Last known stream status: {ORDER_STATUS_TO_STRING_MAP.get(tracked_order_status_from_stream, 'N/A')}")
            else:
                logger.error(f"Failed to submit cancel request for order {tracked_order_id} via OrderPlacer.")
                # Order might have already become terminal, check last known stream status
                if is_order_terminal:
                    logger.info(f"  Order was already terminal with status: {ORDER_STATUS_TO_STRING_MAP.get(tracked_order_status_from_stream)}")

        logger.info("\nFinal details of tracked order from stream events:")
        if tracked_order_details_from_stream:
            logger.info(pprint.pformat(tracked_order_details_from_stream))
        else:
            logger.info("No stream updates were captured for the tracked order ID.")

    except ConfigurationError as e:
        logger.error(f"CONFIGURATION ERROR: {e}")
    except AuthenticationError as e:
        logger.error(f"AUTHENTICATION FAILED: {e}")
    except APIError as e:
        logger.error(f"API ERROR: {e}")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
        if tracked_order_id and not is_order_terminal and order_placer:
            logger.warning(f"Order {tracked_order_id} might still be active. Attempting to cancel due to interrupt...")
            if order_placer.cancel_order(tracked_order_id):
                logger.info("Cancel request for lingering order sent.")
            else:
                logger.error("Failed to send cancel for lingering order.")
    except Exception as e:
        logger.error(f"AN UNEXPECTED ERROR OCCURRED: {e}", exc_info=True)
    finally:
        if user_stream:
            logger.info("Stopping UserHubStream...")
            user_stream.stop()
        logger.info("Order lifecycle tracker example finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track an order's lifecycle using UserHubStream.")
    parser.add_argument(
        "--contract_id", 
        type=str, 
        default=DEFAULT_CONFIG_CONTRACT_ID,
        help="Contract ID for the test order."
    )
    parser.add_argument(
        "--account_id", 
        type=int, 
        default=DEFAULT_CONFIG_ACCOUNT_ID_TO_WATCH,
        help="Account ID to place the order on."
    )
    parser.add_argument(
        "--price_offset",
        type=float,
        default=-20.0, # Default to 20 points below an assumed base for NQ
        help="Price offset from a base price to set the limit order (e.g., -10 for 10 points below base)."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG level logging."
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info("DEBUG logging enabled.")

    if not args.contract_id or not args.account_id or args.account_id <= 0:
        logger.error("A valid --contract_id and positive --account_id must be provided or set in .env.")
        sys.exit(1)

    run_order_lifecycle_example(
        contract_id=args.contract_id,
        account_id=args.account_id,
        limit_price_offset=args.price_offset
    )