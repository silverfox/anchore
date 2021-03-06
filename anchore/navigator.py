import os
import re
import subprocess
import random
import shutil
import logging
import time

from anchore import anchore_utils
from anchore.util import scripting, contexts

class Navigator(object):
    _logger = logging.getLogger(__name__)

    def __init__(self, anchore_config, imagelist, allimages, docker_cli=None):
        self.config = anchore_config
        self.allimages = allimages
        self.anchore_datadir = self.config['image_data_store']
        self.images = list()

        self.images = anchore_utils.image_context_add(imagelist, allimages, docker_cli=docker_cli, anchore_datadir=self.anchore_datadir, tmproot=self.config['tmpdir'], anchore_db=contexts['anchore_db'], must_be_analyzed=True, must_load_all=True)

    def add_images(self, imagelist):
        newimages = anchore_utils.image_context_add(imagelist, self.allimages, docker_cli=contexts['docker_cli'], anchore_datadir=self.anchore_datadir, tmproot=self.config['tmpdir'], anchore_db=contexts['anchore_db'], must_be_analyzed=True, must_load_all=True)

        self.images = list(set(self.images) | set(newimages))

    def generate_reports(self):
        ret = {}
        for imageId in self.images:
            image = self.allimages[imageId]
            baseId = image.get_earliest_base()
            bimage = self.allimages[baseId]

            image_report = image.get_image_report()
            analysis_report = image.get_analysis_report()
            compare_report = image.get_compare_report()
            gates_report = image.get_gates_report()
            gates_eval_report = image.get_gates_eval_report()

            record = {
                'image_report': image_report,
                'analysis_report': analysis_report,
                'compare_report': compare_report,
                'gates_report': gates_report,
                'gates_eval_report': gates_eval_report,
                # set up printable result
                'result': {
                    'header':['ImageId', 'Type', 'CurrentTags', 'AllTags', 'GateStatus', 'Counts', 'BaseDiffs'],
                    'rows': list()
                }
            }

            shortId = image.meta['shortId']
            usertype = str(image.get_usertype())
            currtags = ','.join(image.get_alltags_current())
            alltags = ','.join(image.get_alltags_ever())

            gateaction = 'UNKNOWN'
            for g in gates_eval_report:
                if g['trigger'] == 'FINAL':
                    gateaction = g['action']
                    break

            pnum = str(len(analysis_report['package_list']['pkgs.all']))
            fnum = str(len(analysis_report['file_list']['files.all']))
            snum = str(len(analysis_report['file_suids']['files.suids']))
            analysis_str = ' '.join(["PKGS="+pnum, "FILES="+fnum, "SUIDFILES="+snum])

            compare_str = "N/A"
            if baseId in compare_report:
                pnum = str(len(compare_report[baseId]['package_list']['pkgs.all']))
                fnum = str(len(compare_report[baseId]['file_list']['files.all']))
                snum = str(len(compare_report[baseId]['file_suids']['files.suids']))
                compare_str = ' '.join(["PKGS="+pnum, "FILES="+fnum, "SUIDFILES="+snum])

            #row = [ fill(x, 80) for x in [ shortId, usertype, currtags, alltags, gateaction, analysis_str, compare_str ] ]
            row = [ shortId, usertype, currtags, alltags, gateaction, analysis_str, compare_str ]

            record['result']['rows'].append(row)

            ret[imageId] = record
        return ret

    def get_images(self):
        return(self.images)

    def get_dockerfile_contents(self):
        result = {}
        for imageId in self.images:
            image = self.allimages[imageId]
            #result[imageId] = image.get_dockerfile_contents()
            record = {'result':{}}
            record['result']['header'] = ['ImageId', 'Mode', 'DockerfileContents']
            record['result']['rows'] = list()
            (dbuf, mode) = image.get_dockerfile_contents()
            record['result']['rows'].append([image.meta['shortId'], mode, dbuf])
            result[imageId] = record
        return(result)

    def get_familytree(self):
        result = {}
        for imageId in self.images:
            image = self.allimages[imageId]
            record = {'result':{}}
            record['result']['header'] = ['ImageId', 'Current Repo/Tags', 'Past Repo/Tags', 'ImageType']
            record['result']['rows'] = list()
            for fid in image.get_familytree():
                fimage = self.allimages[fid]
                fidstr = fimage.meta['shortId']
                curr_tags = ','.join(fimage.get_alltags_current())
                past_tags = ','.join(fimage.get_alltags_past())
                
                usertype = fimage.get_usertype()
                if usertype == "anchorebase":
                    userstr = "Anchore Base Image"
                elif usertype == "oldanchorebase":
                    userstr = "Previous Anchore Base Image"
                elif usertype == "user":
                    userstr = "User Image"
                else:
                    userstr = "Intermediate"

                record['result']['rows'].append([fidstr, curr_tags, past_tags, userstr])

            result[imageId] = record
            
        return(result)

    def get_layers(self):
        result = {}
        for imageId in self.images:
            image = self.allimages[imageId]
            record = {'result':{}}
            record['result']['header'] = ['LayerId']
            record['result']['rows'] = list()
            for fid in image.get_layers() + [imageId]:
                record['result']['rows'].append([fid])

            result[imageId] = record
            
        return(result)

    def get_taghistory(self):
        result = {}
        for imageId in self.images:
            image = self.allimages[imageId]
            record = {'result':{}}
            record['result']['header'] = ['ImageId', 'Date', 'KnownTags']
            record['result']['rows'] = list()
            for tagtup in image.get_tag_history():
                tstr = time.ctime(int(tagtup[0]))
                tagstr = ','.join(tagtup[1])
                record['result']['rows'].append([image.meta['shortId'], tstr, tagstr])

            try:
                currtags = ','.join(image.get_alltags_current())
                record['result']['rows'].append([image.meta['shortId'], time.ctime(), currtags])
            except:
                pass

            result[imageId] = record
        return(result)

    def unpack(self, destdir='/tmp'):
        ret = {}
        for imageId in self.images:
            image = self.allimages[imageId]
            outdir = image.unpack(docleanup=False, destdir=destdir)
            self._logger.debug("Unpacked image " + image.meta['shortId'] + " in " + outdir)
            ret[imageId] = outdir
        return(ret)

    def run(self):
        return(True)

    def find_query_command(self, action):
        cmdobj = None
        mode = None
        cmd = None
        rc = False
        try:
            cmdobj = scripting.ScriptExecutor(path='/'.join([self.config['scripts_dir'], 'queries']), script_name=action, path_overrides=['/'.join([self.config['anchore_data_dir'], 'user-scripts', 'queries'])])
            cmd = cmdobj.thecmd
            mode = 'query'
            rc = True
        except ValueError as err:
            raise err
        except Exception as err:
            errstr = str(err)
            try:
                cmdobj = scripting.ScriptExecutor(path='/'.join([self.config['scripts_dir'], 'multi-queries']), script_name=action)
                cmd = cmdobj.thecmd
                mode = 'multi-query'
                rc = True
            except ValueError as err:
                raise err
            except Exception as err:
                raise err

        ret = (rc, mode, cmdobj)
        return(ret)

    def execute_query(self, imglist, se, params):
        success = True
        datadir = self.config['image_data_store']
        outputdir = '/'.join([self.config['anchore_data_dir'], "querytmp", "query." + str(random.randint(0, 99999999))])
        os.makedirs(outputdir)

        imgfile = '/'.join([self.config['anchore_data_dir'], "querytmp", "queryimages." + str(random.randint(0, 99999999))])
        anchore_utils.write_plainfile_fromlist(imgfile, imglist)

        cmdline = ' '.join([imgfile, datadir, outputdir])
        if params:
            cmdline = cmdline + ' ' + ' '.join(params)

        meta = {}

        try:
            (cmd, rc, sout) = se.execute(capture_output=True, cmdline=cmdline)
            if rc:
                self._logger.error("Query command ran but execution failed: " )
                self._logger.error("\tCommand: " + ' '.join([se.thecmd, cmdline]))
                self._logger.error("\tCommand output:\n" + str(sout))
                self._logger.error("\tExit code: " + str(rc))
                raise Exception("Query ran but exited non-zero.")
        except Exception as err:
            raise Exception("Query execution failed: " + str(err))
        else:
            try:
                outputs = os.listdir(outputdir)
                if len(outputs) <= 0:
                    raise Exception("No output files found after executing query command\n\tCommand Output:\n"+sout+"\n\tInfo: Query command should have produced an output file in: " + outputdir)

                orows = list()
                ofile = outputs[0]

                try:
                    frows = anchore_utils.read_kvfile_tolist('/'.join([outputdir, ofile]))
                    header = frows[0]
                    rowlen = len(header)
                    for row in frows[1:]:
                        if len(row) != rowlen:
                            raise Exception("Number of columns in data row ("+str(len(row))+") is not equal to number of columns in header ("+str(rowlen)+")\n\tHeader: "+str(header)+"\n\tOffending Row: "+str(row))
                        orows.append(row)
                except Exception as err:
                    raise err 

                meta['queryparams'] = ','.join(params)
                meta['querycommand'] = cmd
                meta['result'] = {}
                meta['result']['header'] = header
                meta['result']['rowcount'] = len(orows)
                try:
                    meta['result']['colcount'] = len(orows[0])
                except:
                    meta['result']['colcount'] = 0
                meta['result']['rows'] = orows

            except Exception as err:
                self._logger.error("Query output handling failed: ")
                self._logger.error("\tCommand: " + ' '.join(cmd))
                self._logger.error("\tException: " + str(err))
                success = False
        finally:
            os.remove(imgfile)

        ret = [success, cmd, outputdir, meta]
        return(ret)

    def list_query_commands(self, command=None):
        result = {}

        record = {'result':{}}
        record['result']['header'] = ["Query", "HelpString"]
        record['result']['rows'] = list()

        if command:
            try:
                (rc, command_type, se) = self.find_query_command(command)
                if rc:
                    (cmd, rc, sout) = se.execute(capture_output=True, cmdline='help')
                    if rc == 0:
                        record['result']['rows'].append([command, sout])
            except Exception as err:
                pass
                
        else:
            querydir = '/'.join([self.config['scripts_dir'], "queries"])
            mquerydir = '/'.join([self.config['scripts_dir'], "multi-queries"])
            uquerydir = '/'.join([self.config['anchore_data_dir'], "user-scripts", 'queries'])
            umquerydir = '/'.join([self.config['anchore_data_dir'], "user-scripts", 'multi-queries'])

            for dd in [querydir, mquerydir, uquerydir, umquerydir]:
                if not os.path.exists(dd):
                    continue
                for d in os.listdir(dd):
                    command = re.sub("(\.py|\.sh)$", "", d)
                    try:
                        (rc, command_type, se) = self.find_query_command(command)
                        if rc:
                            (cmd, rc, sout) = se.execute(capture_output=True, cmdline='help')
                            if rc == 0:
                                record['result']['rows'].append([command, sout])
                    except Exception as err:
                        pass

        result['list_query_commands'] = record
        return(result)

    def run_query(self, query):
        result = {}

        if len(query) == 0:
            return(self.list_query_commands())
        elif len(query) == 1:
            action = query[0]
            params = ['help']
        else:
            action = query[0]
            params = query[1:]

        if re.match(r".*(\.\.|~|/).*", action) or re.match(r"^\..*", action):
            self._logger.error("invalid query string (bad characters in string)")
            return(False)
                    
        try:
            (rc, command_type, se) = self.find_query_command(action)
        except Exception as err:
             raise err

        if not rc:
            self._logger.error("cannot find query command in Anchore query directory: " + action + "(.py|.sh)")
            return(False)

        if params and params[0] == 'help':
            return(self.list_query_commands(action))

        outputdir = None

        if command_type == 'query':
            for imageId in self.images:
                (rc, cmd, outputdir, output) = self.execute_query([imageId], se, params)
                if rc:
                    result[imageId] = output

        elif command_type == 'multi-query':
            (rc, cmd, outputdir, output) = self.execute_query(self.images, se, params)
            if rc:
                result['multi'] = output

        if outputdir:
            shutil.rmtree(outputdir)

        return(result)

