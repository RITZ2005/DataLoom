import path from 'path'
import { readFileSync, writeFileSync, accessSync, R_OK, W_OK, readdirSync, statSync } from 'fs'
import gulp from 'gulp'
import { ensureDirSync, ensureFileSync } from 'fs-extra/esm'
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const { join, basename, extname } = path
const { task } = gulp

let objToWrite = {}
let paths = {
  langFolder: join(__dirname, 'src/lang/'),
  srcFolder: join(__dirname, 'src/')
}

task('geni18n', function (done) {
  // let projPath = readlineSync.question("Please enter project path (path of 'src' folder)  ")
  // projPath = projPath + '/'
  let projPath = paths.srcFolder
  readPrevi18n()
  backUpI18nFile(projPath)
  i18nGenerator(projPath, ['en'], 'en')
  done()
})

function backUpI18nFile (projPath) {
  let d = new Date()
  let dformat = [paddingZero(d.getDate()), paddingZero(d.getMonth() + 1),
    paddingZero(d.getFullYear())].join('_') + '_' +
    [paddingZero(d.getHours()),
      paddingZero(d.getMinutes()),
      paddingZero(d.getSeconds()), paddingZero(d.getMilliseconds())].join('_')
  let backUpFolderPath = paths.langFolder + 'backup'
  let backUpFilePath = backUpFolderPath + '/en_' + dformat + '.json'
  try {
    ensureDirSync(backUpFolderPath)
  } catch (error) {
    console.log('Cannot create backup folder...')
  }
  let enFilePath = paths.langFolder + 'en.json'
  let content = readFileSync(enFilePath, 'utf8')
  writeFileSync(backUpFilePath, JSON.parse(JSON.stringify(content)))
}

function paddingZero (number) {
  if (number <= 9) {
    let temp = '0' + number.toString()
    return temp
  }
  return number.toString()
}

function createDvJson (projPath, objToWrite) {
  for (let key in objToWrite) {
    if (typeof objToWrite[key] === 'object') {
      let temp = objToWrite[key]
      for (let newKey in temp) {
        if (temp.hasOwnProperty(newKey)) {
          temp[newKey] = newKey
        }
      }
    }
  }
  let dvFilePath = paths.langFolder + 'dv.json'
  writeFileSync(dvFilePath, JSON.stringify(objToWrite))
}

function readPrevi18n () {
  let enFilePath = paths.langFolder + 'en.json'
  try {
    accessSync(enFilePath, R_OK | W_OK)
    let content = readFileSync(enFilePath, 'utf8')
    objToWrite = JSON.parse(content)
  } catch (e) {
    console.log('en.json file is missing...')
    ensureFileSync(enFilePath)
    console.log('Created en.json file...')
    objToWrite = {}
  }
}

function i18nGenerator (projPath, langArray, defaultLanguage) {
  let fileList = walkSync(projPath)
  let flag = 0
  let i
  let len = fileList.length
  let regexString = `([$]t[(]('|")##(.+?)##)(\\s*\\s*)(@@([\\s\\S]*?)@@('|")[)])`
  let regex = new RegExp(regexString, 'gi')

  if (fileList != null && fileList !== undefined && fileList.length > 0) {
    for (i = 0; i < fileList.length; i++) {
      flag++
      if (flag === len) {
        let fileList = walkSync(projPath)
        let i; let len = fileList.length
        if (fileList !== null && fileList !== undefined && fileList.length > 0) {
          for (i = 0; i < len; i++) {
            let file = fileList[i]
            let keyPrefix = basename(file).split('.')[0]
            let content = readFileSync(file, 'utf8')
            let i18nContentsToBeReplaced = content.match(regex)
            let translatedAdded = content
            if (i18nContentsToBeReplaced != null && i18nContentsToBeReplaced !== '' && i18nContentsToBeReplaced !== undefined && i18nContentsToBeReplaced.length > 0) {
              for (let j = 0; j < i18nContentsToBeReplaced.length; j++) {
                let extractKeyFrom = i18nContentsToBeReplaced[j].toString()
                let key = extractKeyFrom.substring(extractKeyFrom.indexOf('##') + 2, extractKeyFrom.lastIndexOf('##')).trim()
                let value = extractKeyFrom.substring(extractKeyFrom.indexOf('@@') + 2, extractKeyFrom.lastIndexOf('@@')).trim()
                // let replacement = "{{'" + key + "' | translate}}";
                let replacement = "$t('" + keyPrefix + '.' + key + "')"
                // console.log('keyPrefix + key', keyPrefix, key)
                translatedAdded = translatedAdded.replace(extractKeyFrom, replacement)
                prepareI18nObject(keyPrefix, key, value)
              }
              writeFileSync(file, translatedAdded)
            }
            if (i === (len - 1)) {
              console.log('\n\n')
              console.log('Internationalization successfully done on ' + (i + 1) + ' files')
              console.log('\n\n')
              let enFilePath = paths.langFolder + 'en.json'
              writeFileSync(enFilePath, JSON.stringify(objToWrite))
              createDvJson(projPath, objToWrite)
            }
          }
        }
      }
    }
  }
}

let walkSync = function (dir, filelist) {
  let files = readdirSync(dir)
  filelist = filelist || []
  files.forEach(function (file) {
    if (statSync(dir + file).isDirectory()) {
      filelist = walkSync(dir + file + '/', filelist)
    } else {
      if (extname(file) === '.vue') {
        filelist.push(dir + file)
      }
    }
  })
  return filelist
}

function prepareI18nObject (keyPrefix, key, value) {
  if (!objToWrite.hasOwnProperty(keyPrefix)) {
    objToWrite[keyPrefix] = {}
  }
  let parentObj = objToWrite[keyPrefix]
  parentObj[key] = value
}
